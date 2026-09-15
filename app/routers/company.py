import uuid
from typing import List
from fastapi import APIRouter, Request, Form, Cookie, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.routers.portfolios import TURKEY_DISTRICTS
from app.utils.notifier import send_notification

router = APIRouter(prefix="/company", tags=["Company"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def get_company_user(user_id: str):
    if not user_id:
        return None
    clean_id = str(user_id).strip()
    try:
        u_res = supabase.table("users").select("*").eq("id", clean_id).single().execute()
        user = u_res.data
        if user and str(user.get("firma_tipi") or "").lower() in ["sirket", "proje_firmasi", "developer"]:
            return user
    except Exception:
        return None
    return None

# ================= 1. ŞİRKET ANA SAYFASI (DASHBOARD) =================
@router.get("/dashboard", response_class=HTMLResponse)
def get_company_dashboard(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    company_name = user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici"

    active_projects_count = 0
    total_partners_count = 0
    month_registrations_count = 0
    meeting_customers_count = 0
    reservations_count = 0
    sales_count = 0
    total_sales_volume = 0
    total_commission_paid = 0

    recent_projects = []
    featured_campaign_project = None

    try:
        p_res = supabase.table("projects").select("*").eq("firma_id", clean_id).order("created_at", desc=True).execute()
        all_projects = p_res.data or []
        active_projects_count = len([p for p in all_projects if p.get("durum") == "Aktif"])
        recent_projects = all_projects[:6]

        for p in all_projects:
            if p.get("durum") == "Aktif":
                featured_campaign_project = p
                break

        p_ids = [p["id"] for p in all_projects]

        if p_ids:
            part_res = supabase.table("project_partners").select("id", count="exact").in_("project_id", p_ids).eq("durum", "Aktif").execute()
            total_partners_count = part_res.count or 0

            reg_res = supabase.table("project_customer_registrations").select(
                "*, projects(ad, min_fiyat, max_fiyat, partner_komisyon_orani)"
            ).in_("project_id", p_ids).execute()
            all_regs = reg_res.data or []
            month_registrations_count = len(all_regs)

            proj_stats = {p["id"]: {"partners": set(), "sales": 0} for p in all_projects}

            for r in all_regs:
                st = str(r.get("durum") or "").strip().lower()
                pid = r.get("project_id")
                aid = r.get("agent_id")

                if pid in proj_stats and aid:
                    proj_stats[pid]["partners"].add(aid)

                if st == "görüşmede":
                    meeting_customers_count += 1
                elif st in ["satış yapılıyor", "satis yapiliyor", "rezervasyon"]:
                    reservations_count += 1
                elif st in ["satış yapıldı", "satis yapildi", "tamamlandı"]:
                    sales_count += 1
                    if pid in proj_stats:
                        proj_stats[pid]["sales"] += 1

                    satis_bedeli = r.get("gerceklesen_satis_bedeli")
                    if not satis_bedeli or satis_bedeli == 0:
                        p_info = r.get("projects") or {}
                        satis_bedeli = p_info.get("min_fiyat") or 0

                    total_sales_volume += int(satis_bedeli)
                    komisyon_orani = float((r.get("projects") or {}).get("partner_komisyon_orani") or 3.0)
                    total_commission_paid += int(satis_bedeli * (komisyon_orani / 100))

            for p in recent_projects:
                p["partner_count"] = len(proj_stats.get(p["id"], {}).get("partners", set()))
                p["sales_count"] = proj_stats.get(p["id"], {}).get("sales", 0)

    except Exception as e:
        print(f"[DASHBOARD METRİK HATASI]: {e}")

    return templates.TemplateResponse(
        request=request,
        name="company/dashboard.html",
        context={
            "user": user,
            "company_name": company_name,
            "active_projects_count": active_projects_count,
            "total_partners_count": total_partners_count,
            "month_registrations_count": month_registrations_count,
            "meeting_customers_count": meeting_customers_count,
            "reservations_count": reservations_count,
            "sales_count": sales_count,
            "total_sales_volume": total_sales_volume,
            "total_commission_paid": total_commission_paid,
            "recent_projects": recent_projects,
            "featured_project": featured_campaign_project
        }
    )

# ================= 2. PROJELERİM LİSTESİ =================
@router.get("/projects", response_class=HTMLResponse)
def get_company_projects(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    try:
        projects_res = supabase.table("projects").select("*").eq("firma_id", clean_id).order("created_at", desc=True).execute()
        my_projects = projects_res.data or []
    except Exception:
        my_projects = []

    return templates.TemplateResponse(
        request=request,
        name="company/projects.html",
        context={"user": user, "projects": my_projects}
    )

# ================= 3. PROJE EKLE =================
@router.get("/projects/add", response_class=HTMLResponse)
def get_add_project(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="company/project_add.html",
        context={
            "user": user, 
            "company_name": user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici",
            "turkey_data": TURKEY_DISTRICTS
        }
    )

@router.post("/projects/add")
async def post_add_project(
    request: Request,
    user_id: str = Cookie(None),
    ad: str = Form(...),
    il: str = Form("İstanbul"),
    ilce: str = Form(...),
    bolge: str = Form(None),
    proje_tipi: str = Form("Konut"),
    teslim_tarihi: str = Form(None),
    min_fiyat: int = Form(0),
    max_fiyat: int = Form(0),
    stok_adeti: int = Form(1),
    toplam_unite: int = Form(1),
    partner_komisyon_orani: float = Form(3.0),
    kurucu_ofis_komisyon_orani: float = Form(4.0),
    aciklama: str = Form(None),
    odeme_plani: str = Form(None),
    daire_tipleri: List[str] = Form([]),
    kapak_fotografi: UploadFile = File(None),
    galeri_fotograflari: List[UploadFile] = File([]),
    kat_plani_dosyalari: List[UploadFile] = File([]),
    brosur_dosyasi: UploadFile = File(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])

    cover_url = None
    if kapak_fotografi and kapak_fotografi.filename:
        try:
            b_img = await kapak_fotografi.read()
            if len(b_img) > 0:
                ext = kapak_fotografi.filename.split(".")[-1].lower() if "." in kapak_fotografi.filename else "jpg"
                f_name = f"cover_{uuid.uuid4().hex[:8]}.{ext}"
                supabase.storage.from_("portfolios").upload(
                    path=f_name,
                    file=b_img,
                    file_options={"content-type": kapak_fotografi.content_type or f"image/{ext}"}
                )
                cover_url = supabase.storage.from_("portfolios").get_public_url(f_name)
        except Exception as e_up:
            print(f"[KAPAK YUKLEME HATASI]: {e_up}")

    gallery_urls = []
    if galeri_fotograflari:
        for gf in galeri_fotograflari:
            if gf.filename:
                try:
                    b_gal = await gf.read()
                    if len(b_gal) > 0:
                        ext = gf.filename.split(".")[-1].lower() if "." in gf.filename else "jpg"
                        g_name = f"gal_{uuid.uuid4().hex[:8]}.{ext}"
                        supabase.storage.from_("portfolios").upload(
                            path=g_name,
                            file=b_gal,
                            file_options={"content-type": gf.content_type or f"image/{ext}"}
                        )
                        gallery_urls.append(supabase.storage.from_("portfolios").get_public_url(g_name))
                except Exception as e_gal:
                    print(f"[GALERİ YUKLEME HATASI]: {e_gal}")

    floor_plan_urls = []
    if kat_plani_dosyalari:
        for kf in kat_plani_dosyalari:
            if kf.filename:
                try:
                    b_kp = await kf.read()
                    if len(b_kp) > 0:
                        ext = kf.filename.split(".")[-1].lower() if "." in kf.filename else "jpg"
                        kp_name = f"plan_{uuid.uuid4().hex[:8]}.{ext}"
                        supabase.storage.from_("portfolios").upload(
                            path=kp_name,
                            file=b_kp,
                            file_options={"content-type": kf.content_type or f"image/{ext}"}
                        )
                        floor_plan_urls.append(supabase.storage.from_("portfolios").get_public_url(kp_name))
                except Exception as e_kp:
                    print(f"[KAT PLANI YUKLEME HATASI]: {e_kp}")

    brosur_url = None
    if brosur_dosyasi and brosur_dosyasi.filename:
        try:
            b_pdf = await brosur_dosyasi.read()
            if len(b_pdf) > 0:
                ext = brosur_dosyasi.filename.split(".")[-1].lower() if "." in brosur_dosyasi.filename else "pdf"
                pdf_name = f"brochure_{uuid.uuid4().hex[:8]}.{ext}"
                supabase.storage.from_("portfolios").upload(
                    path=pdf_name,
                    file=b_pdf,
                    file_options={"content-type": brosur_dosyasi.content_type or "application/pdf"}
                )
                brosur_url = supabase.storage.from_("portfolios").get_public_url(pdf_name)
        except Exception as e_pdf:
            print(f"[BROŞÜR YUKLEME HATASI]: {e_pdf}")

    try:
        final_desc = (aciklama or "").strip()
        if daire_tipleri:
            types_str = ", ".join(daire_tipleri)
            final_desc = f"{final_desc}\n\n[DAIRE_TIPLERI]: {types_str}".strip()

        project_payload = {
            "firma_id": clean_id,
            "ad": ad.strip(),
            "ulke": "Türkiye",
            "il": il.strip() if il else "İstanbul",
            "ilce": ilce.strip(),
            "bolge": bolge.strip() if bolge else None,
            "proje_tipi": proje_tipi.strip(),
            "teslim_tarihi": teslim_tarihi.strip() if teslim_tarihi else None,
            "min_fiyat": int(min_fiyat) if min_fiyat else 0,
            "max_fiyat": int(max_fiyat) if max_fiyat else 0,
            "stok_adeti": int(stok_adeti) if stok_adeti else 1,
            "toplam_unite": int(toplam_unite) if toplam_unite else 1,
            "partner_komisyon_orani": float(partner_komisyon_orani),
            "kurucu_ofis_komisyon_orani": float(kurucu_ofis_komisyon_orani),
            "aciklama": final_desc if final_desc else None,
            "odeme_plani": odeme_plani.strip() if odeme_plani else None,
            "kapak_fotografi": cover_url,
            "galeri": gallery_urls,
            "kat_planlari": floor_plan_urls,
            "brosur_url": brosur_url,
            "durum": "Aktif"
        }
        supabase.table("projects").insert(project_payload).execute()
        return RedirectResponse(url="/company/projects", status_code=303)
    except Exception as e:
        print(f"[PROJE KAYDETME HATASI]: {e}")
        return templates.TemplateResponse(
            request=request,
            name="company/project_add.html",
            context={
                "user": user,
                "company_name": user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici",
                "error": f"Proje kaydedilemedi: {str(e)}",
                "turkey_data": TURKEY_DISTRICTS
            }
        )

# ================= 4. MÜŞTERİ TESCİLLERİ =================
@router.get("/registrations", response_class=HTMLResponse)
def get_company_registrations(request: Request, page: int = 1, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    company_name = user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici"
    
    registrations = []
    total_count = 0
    per_page = 6
    page = max(1, int(page))

    try:
        p_res = supabase.table("projects").select("id, ad, durum").eq("firma_id", clean_id).execute()
        my_projects = p_res.data or []
        p_ids = [item["id"] for item in my_projects]

        if p_ids:
            c_res = supabase.table("project_customer_registrations").select("id", count="exact").in_("project_id", p_ids).execute()
            total_count = c_res.count or 0

            start = (page - 1) * per_page
            end = start + per_page - 1

            reg_res = supabase.table("project_customer_registrations").select(
                "*, projects(ad, durum, partner_komisyon_orani), users:agent_id(ad_soyad, telefon, sirket_unvani)"
            ).in_("project_id", p_ids).order("created_at", desc=True).range(start, end).execute()
            
            registrations = reg_res.data or []
    except Exception as e:
        print(f"[COMPANY REGISTRATIONS HATASI]: {e}")
        registrations = []

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request,
        name="company/registrations.html",
        context={
            "user": user,
            "company_name": company_name,
            "registrations": registrations,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count
        }
    )

@router.post("/registrations/update-status")
def post_update_registration_status(
    request: Request,
    user_id: str = Cookie(None),
    registration_id: str = Form(...),
    yeni_durum: str = Form(...)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    try:
        clean_reg_id = registration_id.strip()
        new_status = yeni_durum.strip()

        # Mevcut durumu sorgula
        cur_reg = supabase.table("project_customer_registrations").select(
            "durum, gerceklesen_satis_bedeli, projects(durum)"
        ).eq("id", clean_reg_id).single().execute()

        if not cur_reg.data:
            return RedirectResponse(url="/company/registrations", status_code=303)

        current_st = str(cur_reg.data.get("durum") or "").strip().lower()

        # KURAL 1: Zaten Satış Yapıldı ise başka aşamaya geri alınamaz
        if current_st in ["satış yapıldı", "satis yapildi", "tamamlandı"]:
            return RedirectResponse(url="/company/registrations?err=already_completed", status_code=303)

        # KURAL 2: 'Satış Yapıldı' doğrudan buradan seçilemez; Satış Yönetimi sekmesinden kapatılmalıdır
        if new_status.lower() in ["satış yapıldı", "satis yapildi"]:
            return RedirectResponse(url="/company/sales?err=finalize_via_sales_tab", status_code=303)

        # Proje pasifse işlem engeli
        if cur_reg.data.get("projects", {}).get("durum") == "Pasif":
            return RedirectResponse(url="/company/registrations?err=project_inactive", status_code=303)

        supabase.table("project_customer_registrations").update({"durum": new_status}).eq("id", clean_reg_id).execute()

        reg_data = supabase.table("project_customer_registrations").select(
            "agent_id, musteri_ad_soyad, projects(ad)"
        ).eq("id", clean_reg_id).single().execute()

        if reg_data.data:
            target_agent_id = reg_data.data.get("agent_id")
            musteri_adi = reg_data.data.get("musteri_ad_soyad")
            proje_adi = reg_data.data.get("projects", {}).get("ad") if reg_data.data.get("projects") else "Proje"

            send_notification(
                user_id=target_agent_id,
                baslik="Müşteri Tescil Durumu Güncellendi",
                icerik=f"'{proje_adi}' projesindeki {musteri_adi} isimli müşterinizin yeni durumu: {new_status}.",
                hedef_url="/collaborations/my?subtab=projeler"
            )
    except Exception as e:
        print(f"[DURUM GUNCELLEME HATASI]: {e}")

    referer = request.headers.get("referer") or "/company/registrations"
    return RedirectResponse(url=referer, status_code=303)

# ================= 5. ŞİRKET BİLDİRİMLERİ =================
@router.get("/notifications", response_class=HTMLResponse)
def get_company_notifications_page(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    notifications = []
    try:
        res = supabase.table("notifications").select("*").eq("user_id", clean_id).order("created_at", desc=True).execute()
        notifications = res.data or []
        
        try:
            supabase.table("notifications").update({"okundu_mu": True}).eq("user_id", clean_id).execute()
        except Exception:
            try:
                supabase.table("notifications").update({"okundu": True}).eq("user_id", clean_id).execute()
            except Exception:
                pass
    except Exception as e:
        print(f"[FİRMA BİLDİRİM LİSTESİ HATASI]: {e}")

    return templates.TemplateResponse(
        request=request,
        name="company/notifications.html",
        context={
            "user": user,
            "company_name": user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici",
            "notifications": notifications
        }
    )

# ================= 6. ŞİRKET PROFİLİ & AYARLAR =================
@router.get("/profile", response_class=HTMLResponse)
@router.get("/settings", response_class=HTMLResponse)
def get_company_profile(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    company_name = user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici"

    total_projects = 0
    total_leads = 0
    total_sales = 0
    settings = {}
    tickets = []

    try:
        p_res = supabase.table("projects").select("id", count="exact").eq("firma_id", clean_id).execute()
        total_projects = p_res.count or 0

        p_ids = [item["id"] for item in (supabase.table("projects").select("id").eq("firma_id", clean_id).execute().data or [])]
        if p_ids:
            reg_res = supabase.table("project_customer_registrations").select("durum").in_("project_id", p_ids).execute()
            all_regs = reg_res.data or []
            total_leads = len(all_regs)
            for r in all_regs:
                st = str(r.get("durum") or "").strip().lower()
                if st in ["satış yapıldı", "satis yapildi", "tamamlandı"]:
                    total_sales += 1

        s_res = supabase.table("user_settings").select("*").eq("user_id", clean_id).execute()
        if s_res.data and len(s_res.data) > 0:
            settings = s_res.data[0]
        else:
            settings = {
                "notify_collab": True,
                "notify_referral": True,
                "notify_messages": True,
                "notify_sales": True
            }

        t_res = supabase.table("support_tickets").select("*").eq("user_id", clean_id).order("created_at", desc=True).limit(5).execute()
        tickets = t_res.data or []

    except Exception as e:
        print(f"[ŞİRKET PROFİL İSTATİSTİK HATASI]: {e}")

    return templates.TemplateResponse(
        request=request,
        name="company/profile.html",
        context={
            "user": user,
            "company_name": company_name,
            "total_projects": total_projects,
            "total_leads": total_leads,
            "total_sales": total_sales,
            "settings": settings,
            "tickets": tickets,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err")
        }
    )

# ================= ŞİRKET BİLGİLERİ VE LOGO GÜNCELLEME (POST) =================
@router.post("/profile")
@router.post("/profile/update")
async def post_update_company_profile(
    request: Request,
    ad_soyad: str = Form(...),
    telefon: str = Form(...),
    sirket_unvani: str = Form(None),
    marka_adi: str = Form(None),
    calisma_bolgesi: str = Form(None),
    profil_foto: UploadFile = File(None),
    user_id: str = Cookie(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    update_data = {
        "ad_soyad": ad_soyad.strip(),
        "telefon": telefon.strip(),
        "sirket_unvani": sirket_unvani.strip() if sirket_unvani else None,
        "marka_adi": marka_adi.strip() if marka_adi else None,
        "calisma_bolgesi": calisma_bolgesi.strip() if calisma_bolgesi else None
    }

    # Yeni logo/fotoğraf yüklendiyse Storage'a at ve URL'i kaydet
    if profil_foto and profil_foto.filename:
        try:
            b_img = await profil_foto.read()
            if len(b_img) > 0:
                ext = profil_foto.filename.split(".")[-1].lower() if "." in profil_foto.filename else "jpg"
                f_name = f"company_{clean_id}_{uuid.uuid4().hex[:6]}.{ext}"
                supabase.storage.from_("portfolios").upload(
                    path=f_name,
                    file=b_img,
                    file_options={"content-type": profil_foto.content_type or f"image/{ext}"}
                )
                update_data["profil_foto"] = supabase.storage.from_("portfolios").get_public_url(f_name)
        except Exception as e_logo:
            print(f"[ŞİRKET LOGO YÜKLEME HATASI]: {e_logo}")

    try:
        supabase.table("users").update(update_data).eq("id", clean_id).execute()
        return RedirectResponse(url="/company/profile?msg=profile_updated", status_code=303)
    except Exception as e:
        print(f"[ŞİRKET PROFİL GÜNCELLEME HATASI]: {e}")
        return RedirectResponse(url="/company/profile?err=profile_failed", status_code=303)

# ================= ŞİRKET ŞİFRE DEĞİŞTİRME (POST) =================
@router.post("/change-password")
@router.post("/settings/change-password")
def post_change_company_password(
    request: Request,
    eski_sifre: str = Form(...),
    yeni_sifre: str = Form(...),
    yeni_sifre_tekrar: str = Form(...),
    user_id: str = Cookie(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])

    if yeni_sifre != yeni_sifre_tekrar:
        return RedirectResponse(url="/company/profile?err=pass_mismatch", status_code=303)

    try:
        u_res = supabase.table("users").select("sifre").eq("id", clean_id).single().execute()
        if not u_res.data or u_res.data.get("sifre") != eski_sifre:
            return RedirectResponse(url="/company/profile?err=wrong_old_pass", status_code=303)

        supabase.table("users").update({"sifre": yeni_sifre}).eq("id", clean_id).execute()
        return RedirectResponse(url="/company/profile?msg=pass_updated", status_code=303)
    except Exception as e:
        print(f"[ŞİRKET ŞİFRE DEĞİŞTİRME HATASI]: {e}")
        return RedirectResponse(url="/company/profile?err=pass_failed", status_code=303)

@router.post("/settings/notifications")
def post_update_company_notifications(
    notify_collab: str = Form(None),
    notify_messages: str = Form(None),
    notify_sales: str = Form(None),
    user_id: str = Cookie(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    payload = {
        "user_id": clean_id,
        "notify_collab": bool(notify_collab),
        "notify_messages": bool(notify_messages),
        "notify_sales": bool(notify_sales)
    }

    try:
        chk = supabase.table("user_settings").select("user_id").eq("user_id", clean_id).execute()
        if chk.data and len(chk.data) > 0:
            supabase.table("user_settings").update(payload).eq("user_id", clean_id).execute()
        else:
            supabase.table("user_settings").insert(payload).execute()
        return RedirectResponse(url="/company/profile?msg=notify_updated", status_code=303)
    except Exception as e:
        print(f"[BİLDİRİM AYAR HATASI]: {e}")
        return RedirectResponse(url="/company/profile?err=notify_failed", status_code=303)

@router.post("/settings/support")
def post_create_company_support_ticket(
    konu: str = Form(...),
    mesaj: str = Form(...),
    user_id: str = Cookie(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    try:
        supabase.table("support_tickets").insert({
            "user_id": clean_id,
            "konu": konu.strip(),
            "mesaj": mesaj.strip(),
            "durum": "beklemede"
        }).execute()
        return RedirectResponse(url="/company/profile?msg=ticket_sent", status_code=303)
    except Exception as e:
        print(f"[BİLET HATASI]: {e}")
        return RedirectResponse(url="/company/profile?err=ticket_failed", status_code=303)

# ================= 7. PARTNERLER =================
@router.get("/partners", response_class=HTMLResponse)
def get_company_partners(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    company_name = user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici"
    partners_list = []

    try:
        p_res = supabase.table("projects").select("id, ad, partner_komisyon_orani, kurucu_ofis_komisyon_orani").eq("firma_id", clean_id).execute()
        my_projects = p_res.data or []
        p_map = {p["id"]: p for p in my_projects}
        p_ids = list(p_map.keys())

        if p_ids:
            part_res = supabase.table("project_partners").select(
                "*, users:agent_id(id, ad_soyad, telefon, eposta, sirket_unvani, profil_foto, calistigi_ilceler)"
            ).in_("project_id", p_ids).order("created_at", desc=True).execute()
            raw_partners = part_res.data or []

            reg_res = supabase.table("project_customer_registrations").select("project_id, agent_id, durum").in_("project_id", p_ids).execute()
            all_regs = reg_res.data or []

            stats_map = {}
            for r in all_regs:
                key = (str(r.get("project_id")), str(r.get("agent_id")))
                if key not in stats_map:
                    stats_map[key] = {"leads": 0, "sales": 0}
                stats_map[key]["leads"] += 1
                st = str(r.get("durum") or "").strip().lower()
                if st in ["satış yapıldı", "satis yapildi", "tamamlandı"]:
                    stats_map[key]["sales"] += 1

            for partner in raw_partners:
                pid = str(partner.get("project_id"))
                aid = str(partner.get("agent_id"))
                
                partner["project_info"] = p_map.get(pid, {"ad": "Proje", "partner_komisyon_orani": 3.0, "kurucu_ofis_komisyon_orani": 4.0})
                stat = stats_map.get((pid, aid), {"leads": 0, "sales": 0})
                partner["lead_count"] = stat["leads"]
                partner["sales_count"] = stat["sales"]
                partners_list.append(partner)

    except Exception as e:
        print(f"[PARTNERS GETIRME HATASI]: {e}")
        partners_list = []

    return templates.TemplateResponse(
        request=request,
        name="company/partners.html",
        context={
            "user": user,
            "company_name": company_name,
            "partners": partners_list
        }
    )

@router.post("/partners/update")
def post_update_partner_status(
    request: Request,
    partner_id: str = Form(...),
    partner_seviyesi: str = Form("Standart"),
    durum: str = Form("Aktif"),
    user_id: str = Cookie(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    try:
        clean_partner_id = partner_id.strip()
        supabase.table("project_partners").update({
            "partner_seviyesi": partner_seviyesi.strip(),
            "durum": durum.strip()
        }).eq("id", clean_partner_id).execute()
    except Exception as e:
        print(f"[PARTNER GUNCELLEME HATASI]: {e}")

    return RedirectResponse(url="/company/partners", status_code=303)

# ================= 8. SATIŞ YÖNETİMİ =================
@router.get("/sales", response_class=HTMLResponse)
def get_company_sales(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    company_name = user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici"

    sales_records = []
    total_volume = 0
    total_commission = 0

    try:
        p_ids = [p["id"] for p in (supabase.table("projects").select("id").eq("firma_id", clean_id).execute().data or [])]
        if p_ids:
            reg_res = supabase.table("project_customer_registrations").select(
                "*, projects(ad, ilce, partner_komisyon_orani), users:agent_id(id, ad_soyad, telefon, sirket_unvani)"
            ).in_("project_id", p_ids).order("created_at", desc=True).execute()

            for r in (reg_res.data or []):
                st = str(r.get("durum") or "").strip().lower()
                if st in ["satış yapıldı", "satis yapildi", "satış yapılıyor", "satis yapiliyor", "rezervasyon", "tamamlandı"]:
                    satis_fiyati = int(r.get("gerceklesen_satis_bedeli") or 0)
                    komisyon_tutari = int(r.get("hesaplanan_komisyon") or 0)

                    if satis_fiyati > 0 and komisyon_tutari == 0:
                        p_oran = float((r.get("projects") or {}).get("partner_komisyon_orani") or 3.0)
                        komisyon_tutari = int(satis_fiyati * (p_oran / 100))
                        r["hesaplanan_komisyon"] = komisyon_tutari

                    if st in ["satış yapıldı", "satis yapildi", "tamamlandı"]:
                        total_volume += satis_fiyati
                        total_commission += komisyon_tutari

                    sales_records.append(r)

    except Exception as e:
        print(f"[SATIŞ YÖNETİMİ HATASI]: {e}")
        sales_records = []

    return templates.TemplateResponse(
        request=request,
        name="company/sales.html",
        context={
            "user": user,
            "company_name": company_name,
            "sales_records": sales_records,
            "total_volume": total_volume,
            "total_commission": total_commission
        }
    )

@router.post("/sales/finalize")
def post_finalize_sale(
    request: Request,
    registration_id: str = Form(...),
    satilan_unite_bilgisi: str = Form(...),
    gerceklesen_satis_bedeli: int = Form(...),
    user_id: str = Cookie(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    try:
        clean_reg_id = registration_id.strip()
        fiyat = int(gerceklesen_satis_bedeli)

        reg_data = supabase.table("project_customer_registrations").select(
            "agent_id, musteri_ad_soyad, projects(ad, partner_komisyon_orani)"
        ).eq("id", clean_reg_id).single().execute()

        komisyon_orani = 3.0
        if reg_data.data and reg_data.data.get("projects"):
            komisyon_orani = float(reg_data.data["projects"].get("partner_komisyon_orani") or 3.0)

        hesaplanan_komisyon = int(fiyat * (komisyon_orani / 100))

        supabase.table("project_customer_registrations").update({
            "durum": "Satış Yapıldı",
            "satilan_unite_bilgisi": satilan_unite_bilgisi.strip(),
            "gerceklesen_satis_bedeli": fiyat,
            "hesaplanan_komisyon": hesaplanan_komisyon
        }).eq("id", clean_reg_id).execute()

        if reg_data.data:
            target_agent_id = reg_data.data.get("agent_id")
            musteri_adi = reg_data.data.get("musteri_ad_soyad")
            proje_adi = reg_data.data["projects"].get("ad") if reg_data.data.get("projects") else "Proje"

            send_notification(
                user_id=target_agent_id,
                baslik="Satış Onaylandı & Komisyon Hak Edildi",
                icerik=f"'{proje_adi}' projesindeki {musteri_adi} isimli müşterinizin satışı onaylandı. Detayları işbirliklerimden inceleyebilirsiniz.",
                hedef_url="/collaborations/my?subtab=projeler"
            )

    except Exception as e:
        print(f"[SATIŞ KAPATMA HATASI]: {e}")

    return RedirectResponse(url="/company/sales", status_code=303)

# ================= 9. RAPORLAR =================
@router.get("/reports", response_class=HTMLResponse)
def get_company_reports(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    company_name = user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici"

    total_leads = 0
    total_sales = 0
    total_revenue = 0
    total_commission = 0
    project_breakdown = []
    top_agents = []

    try:
        p_res = supabase.table("projects").select("id, ad, stok_adeti, toplam_unite, partner_komisyon_orani").eq("firma_id", clean_id).execute()
        my_projects = p_res.data or []
        p_ids = [p["id"] for p in my_projects]

        if p_ids:
            reg_res = supabase.table("project_customer_registrations").select(
                "*, users:agent_id(id, ad_soyad, sirket_unvani)"
            ).in_("project_id", p_ids).execute()
            all_regs = reg_res.data or []
            total_leads = len(all_regs)

            proj_data = {p["id"]: {"ad": p["ad"], "leads": 0, "sales": 0, "revenue": 0, "stok": p.get("stok_adeti") or 0} for p in my_projects}
            agent_data = {}

            for r in all_regs:
                pid = r.get("project_id")
                st = str(r.get("durum") or "").strip().lower()
                aid = r.get("agent_id")
                agent_name = r.get("users", {}).get("ad_soyad") if r.get("users") else "Danışman"

                if pid in proj_data:
                    proj_data[pid]["leads"] += 1

                if aid:
                    if aid not in agent_data:
                        agent_data[aid] = {"name": agent_name, "leads": 0, "sales": 0}
                    agent_data[aid]["leads"] += 1

                if st in ["satış yapıldı", "satis yapildi", "tamamlandı"]:
                    total_sales += 1
                    bedel = int(r.get("gerceklesen_satis_bedeli") or 0)
                    kom = int(r.get("hesaplanan_komisyon") or 0)
                    total_revenue += bedel
                    total_commission += kom

                    if pid in proj_data:
                        proj_data[pid]["sales"] += 1
                        proj_data[pid]["revenue"] += bedel

                    if aid and aid in agent_data:
                        agent_data[aid]["sales"] += 1

            project_breakdown = list(proj_data.values())
            top_agents = sorted(list(agent_data.values()), key=lambda x: (x["sales"], x["leads"]), reverse=True)[:5]

    except Exception as e:
        print(f"[RAPOR VERİLERİ HATASI]: {e}")

    conversion_rate = round((total_sales / total_leads * 100), 1) if total_leads > 0 else 0

    return templates.TemplateResponse(
        request=request,
        name="company/reports.html",
        context={
            "user": user,
            "company_name": company_name,
            "total_leads": total_leads,
            "total_sales": total_sales,
            "total_revenue": total_revenue,
            "total_commission": total_commission,
            "conversion_rate": conversion_rate,
            "project_breakdown": project_breakdown,
            "top_agents": top_agents
        }
    )

# ================= 10. KAMPANYALAR =================
@router.get("/campaigns", response_class=HTMLResponse)
def get_company_campaigns(request: Request, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    company_name = user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici"

    campaigns = []
    my_projects = []

    try:
        p_res = supabase.table("projects").select("id, ad, partner_komisyon_orani").eq("firma_id", clean_id).execute()
        my_projects = p_res.data or []
        p_ids = [p["id"] for p in my_projects]

        if p_ids:
            c_res = supabase.table("project_campaigns").select(
                "*, projects(ad, ilce, il)"
            ).in_("project_id", p_ids).order("created_at", desc=True).execute()
            campaigns = c_res.data or []

    except Exception as e:
        print(f"[KAMPANYA LİSTELEME HATASI]: {e}")
        campaigns = []

    return templates.TemplateResponse(
        request=request,
        name="company/campaigns.html",
        context={
            "user": user,
            "company_name": company_name,
            "campaigns": campaigns,
            "projects": my_projects,
            "msg": request.query_params.get("msg")
        }
    )

@router.post("/campaigns/add")
def post_add_campaign(
    request: Request,
    project_id: str = Form(...),
    baslik: str = Form(...),
    indirim_orani: int = Form(0),
    vade_ay: int = Form(0),
    partner_komisyon_orani: float = Form(4.0),
    bitis_tarihi: str = Form(None),
    kampanya_detayi: str = Form(None),
    user_id: str = Cookie(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_pid = project_id.strip()
    clean_baslik = baslik.strip()

    try:
        campaign_payload = {
            "project_id": clean_pid,
            "baslik": clean_baslik,
            "indirim_orani": int(indirim_orani) if indirim_orani else 0,
            "vade_ay": int(vade_ay) if vade_ay else 0,
            "partner_komisyon_orani": float(partner_komisyon_orani) if partner_komisyon_orani else 4.0,
            "bitis_tarihi": bitis_tarihi.strip() if bitis_tarihi else None,
            "durum": "Aktif"
        }
        supabase.table("project_campaigns").insert(campaign_payload).execute()

        detay_metni = (kampanya_detayi.strip() if kampanya_detayi else 
                       f"%{indirim_orani} İndirim / {vade_ay} Ay Vade Avantajı - %{partner_komisyon_orani} Komisyon")
        
        supabase.table("projects").update({
            "aktif_kampanya_baslik": clean_baslik,
            "aktif_kampanya_detay": detay_metni,
            "kampanya_komisyon_orani": float(partner_komisyon_orani)
        }).eq("id", clean_pid).execute()

        p_info = supabase.table("projects").select("ad").eq("id", clean_pid).single().execute()
        proje_adi = p_info.data.get("ad") if p_info.data else "Proje"

        target_agent_ids = set()
        
        partners = supabase.table("project_partners").select("agent_id").eq("project_id", clean_pid).execute().data or []
        for pt in partners:
            if pt.get("agent_id"):
                target_agent_ids.add(pt["agent_id"])

        registrations = supabase.table("project_customer_registrations").select("agent_id").eq("project_id", clean_pid).execute().data or []
        for rg in registrations:
            if rg.get("agent_id"):
                target_agent_ids.add(rg["agent_id"])

        notif_msg = f"'{proje_adi}' projesinde {clean_baslik} başladı! Danışman komisyonu: %{partner_komisyon_orani}."
        for agent_id in target_agent_ids:
            send_notification(
                user_id=agent_id,
                baslik="Yeni Satış Kampanyası Başladı!",
                icerik=notif_msg,
                hedef_url=f"/projects/detail/{clean_pid}"
            )

        return RedirectResponse(url="/company/campaigns?msg=created", status_code=303)

    except Exception as e:
        print(f"[KAMPANYA OLUŞTURMA HATASI]: {e}")
        return RedirectResponse(url="/company/campaigns?msg=error", status_code=303)

@router.post("/campaigns/toggle-status")
def post_toggle_campaign_status(
    campaign_id: str = Form(...),
    project_id: str = Form(...),
    current_status: str = Form(...),
    user_id: str = Cookie(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    try:
        new_status = "Pasif" if current_status == "Aktif" else "Aktif"
        supabase.table("project_campaigns").update({"durum": new_status}).eq("id", campaign_id.strip()).execute()

        if new_status == "Pasif":
            supabase.table("projects").update({
                "aktif_kampanya_baslik": None,
                "aktif_kampanya_detay": None
            }).eq("id", project_id.strip()).execute()

    except Exception as e:
        print(f"[KAMPANYA DURUM HATASI]: {e}")

    return RedirectResponse(url="/company/campaigns", status_code=303)

# ================= 11. PROJE DÜZENLEME & SİLME =================
@router.get("/projects/edit/{project_id}", response_class=HTMLResponse)
def get_edit_project(request: Request, project_id: str, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    clean_pid = project_id.strip()

    try:
        p_res = supabase.table("projects").select("*").eq("id", clean_pid).eq("firma_id", clean_id).single().execute()
        project = p_res.data
    except Exception as e:
        print(f"[PROJE GETIRME HATASI]: {e}")
        project = None

    if not project:
        return RedirectResponse(url="/company/projects", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="company/project_edit.html",
        context={
            "user": user,
            "company_name": user.get("sirket_unvani") or user.get("ad_soyad") or "Proje Geliştirici",
            "project": project,
            "turkey_data": TURKEY_DISTRICTS
        }
    )

@router.post("/projects/edit/{project_id}")
async def post_edit_project(
    request: Request,
    project_id: str,
    user_id: str = Cookie(None),
    ad: str = Form(...),
    il: str = Form("İstanbul"),
    ilce: str = Form(...),
    bolge: str = Form(None),
    proje_tipi: str = Form("Konut"),
    teslim_tarihi: str = Form(None),
    min_fiyat: int = Form(0),
    max_fiyat: int = Form(0),
    stok_adeti: int = Form(1),
    toplam_unite: int = Form(1),
    partner_komisyon_orani: float = Form(3.0),
    kurucu_ofis_komisyon_orani: float = Form(4.0),
    aciklama: str = Form(None),
    odeme_plani: str = Form(None),
    durum: str = Form("Aktif"),
    kapak_fotografi: UploadFile = File(None),
    galeri_fotograflari: List[UploadFile] = File([]),
    kat_plani_dosyalari: List[UploadFile] = File([]),
    brosur_dosyasi: UploadFile = File(None)
):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    clean_pid = project_id.strip()

    try:
        cur_res = supabase.table("projects").select("*").eq("id", clean_pid).eq("firma_id", clean_id).single().execute()
        current_project = cur_res.data
    except Exception:
        current_project = None

    if not current_project:
        return RedirectResponse(url="/company/projects", status_code=303)

    cover_url = current_project.get("kapak_fotografi")
    gallery_urls = current_project.get("galeri") or []
    floor_plan_urls = current_project.get("kat_planlari") or []
    brosur_url = current_project.get("brosur_url")

    if kapak_fotografi and kapak_fotografi.filename:
        try:
            b_img = await kapak_fotografi.read()
            if len(b_img) > 0:
                ext = kapak_fotografi.filename.split(".")[-1].lower() if "." in kapak_fotografi.filename else "jpg"
                f_name = f"cover_{uuid.uuid4().hex[:8]}.{ext}"
                supabase.storage.from_("portfolios").upload(
                    path=f_name,
                    file=b_img,
                    file_options={"content-type": kapak_fotografi.content_type or f"image/{ext}"}
                )
                cover_url = supabase.storage.from_("portfolios").get_public_url(f_name)
        except Exception as e_up:
            print(f"[KAPAK GUNCELLEME HATASI]: {e_up}")

    if galeri_fotograflari:
        for gf in galeri_fotograflari:
            if gf.filename:
                try:
                    b_gal = await gf.read()
                    if len(b_gal) > 0:
                        ext = gf.filename.split(".")[-1].lower() if "." in gf.filename else "jpg"
                        g_name = f"gal_{uuid.uuid4().hex[:8]}.{ext}"
                        supabase.storage.from_("portfolios").upload(
                            path=g_name,
                            file=b_gal,
                            file_options={"content-type": gf.content_type or f"image/{ext}"}
                        )
                        gallery_urls.append(supabase.storage.from_("portfolios").get_public_url(g_name))
                except Exception as e_gal:
                    print(f"[GALERI GUNCELLEME HATASI]: {e_gal}")

    if kat_plani_dosyalari:
        for kf in kat_plani_dosyalari:
            if kf.filename:
                try:
                    b_kp = await kf.read()
                    if len(b_kp) > 0:
                        ext = kf.filename.split(".")[-1].lower() if "." in kf.filename else "jpg"
                        kp_name = f"plan_{uuid.uuid4().hex[:8]}.{ext}"
                        supabase.storage.from_("portfolios").upload(
                            path=kp_name,
                            file=b_kp,
                            file_options={"content-type": kf.content_type or f"image/{ext}"}
                        )
                        floor_plan_urls.append(supabase.storage.from_("portfolios").get_public_url(kp_name))
                except Exception as e_kp:
                    print(f"[KAT PLANI GUNCELLEME HATASI]: {e_kp}")

    if brosur_dosyasi and brosur_dosyasi.filename:
        try:
            b_pdf = await brosur_dosyasi.read()
            if len(b_pdf) > 0:
                ext = brosur_dosyasi.filename.split(".")[-1].lower() if "." in brosur_dosyasi.filename else "pdf"
                pdf_name = f"brochure_{uuid.uuid4().hex[:8]}.{ext}"
                supabase.storage.from_("portfolios").upload(
                    path=pdf_name,
                    file=b_pdf,
                    file_options={"content-type": brosur_dosyasi.content_type or "application/pdf"}
                )
                brosur_url = supabase.storage.from_("portfolios").get_public_url(pdf_name)
        except Exception as e_pdf:
            print(f"[BROSUR GUNCELLEME HATASI]: {e_pdf}")

    try:
        update_payload = {
            "ad": ad.strip(),
            "il": il.strip() if il else "İstanbul",
            "ilce": ilce.strip(),
            "bolge": bolge.strip() if bolge else None,
            "proje_tipi": proje_tipi.strip(),
            "teslim_tarihi": teslim_tarihi.strip() if teslim_tarihi else None,
            "min_fiyat": int(min_fiyat) if min_fiyat else 0,
            "max_fiyat": int(max_fiyat) if max_fiyat else 0,
            "stok_adeti": int(stok_adeti) if stok_adeti else 0,
            "toplam_unite": int(toplam_unite) if toplam_unite else 0,
            "partner_komisyon_orani": float(partner_komisyon_orani),
            "kurucu_ofis_komisyon_orani": float(kurucu_ofis_komisyon_orani),
            "aciklama": aciklama.strip() if aciklama else None,
            "odeme_plani": odeme_plani.strip() if odeme_plani else None,
            "durum": durum.strip(),
            "kapak_fotografi": cover_url,
            "galeri": gallery_urls,
            "kat_planlari": floor_plan_urls,
            "brosur_url": brosur_url
        }
        supabase.table("projects").update(update_payload).eq("id", clean_pid).eq("firma_id", clean_id).execute()
        return RedirectResponse(url="/company/projects", status_code=303)
    except Exception as e:
        print(f"[PROJE GUNCELLEME KRITIK HATA]: {e}")
        return templates.TemplateResponse(
            request=request,
            name="company/project_edit.html",
            context={
                "user": user,
                "project": current_project,
                "company_name": user.get("sirket_unvani") or "Proje Geliştirici",
                "error": f"Güncelleme başarısız: {str(e)}",
                "turkey_data": TURKEY_DISTRICTS
            }
        )

@router.post("/projects/delete/{project_id}")
def post_delete_project(project_id: str, user_id: str = Cookie(None)):
    user = get_company_user(user_id)
    if not user:
        return RedirectResponse(url="/login?type=company", status_code=303)

    clean_id = str(user["id"])
    clean_pid = project_id.strip()

    try:
        reg_chk = supabase.table("project_customer_registrations").select("id", count="exact").eq("project_id", clean_pid).execute()
        has_registrations = (reg_chk.count or 0) > 0

        if has_registrations:
            supabase.table("projects").update({"durum": "Pasif"}).eq("id", clean_pid).eq("firma_id", clean_id).execute()
        else:
            supabase.table("projects").delete().eq("id", clean_pid).eq("firma_id", clean_id).execute()

    except Exception as e:
        print(f"[PROJE SILME HATASI]: {e}")

    return RedirectResponse(url="/company/projects", status_code=303)