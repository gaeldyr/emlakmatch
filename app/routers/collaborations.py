from datetime import datetime, timezone
from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.security import is_relationship_blocked
from app.utils.notifier import send_notification

router = APIRouter(prefix="/collaborations", tags=["Collaborations"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ================= 1. İŞBİRLİKLERİM LİSTESİ =================
@router.get("/my", response_class=HTMLResponse)
@router.get("/pending", response_class=HTMLResponse)
def get_my_collaborations(
    request: Request, 
    tab: str = "aktif", 
    subtab: str = "portfoyler", 
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    filtered_list = []
    try:
        res = (
            supabase.table("collaboration_requests")
            .select("*")
            .or_(f"talep_alan_id.eq.{clean_user_id},talep_gonderen_id.eq.{clean_user_id}")
            .order("created_at", desc=True)
            .execute()
        )
        raw_collabs = res.data or []

        rev_res = (
            supabase.table("agent_reviews")
            .select("collaboration_id")
            .eq("reviewer_id", clean_user_id)
            .execute()
        )
        reviewed_collab_ids = {
            str(r.get("collaboration_id")).strip()
            for r in (rev_res.data or [])
            if r.get("collaboration_id")
        }

        for c in raw_collabs:
            durum = str(c.get("durum") or "").strip().lower()

            is_match = False
            if tab == "aktif" and durum in ["aktif", "onaylandı", "basari_onayi_bekleniyor"]:
                is_match = True
            elif tab == "bekleyen" and durum in ["beklemede", "bekleyen"]:
                is_match = True
            elif tab == "tamamlanan" and durum in ["tamamlandı", "reddedildi", "iptal edildi", "başarısız"]:
                is_match = True

            if is_match:
                port_id = c.get("ilgili_ilan_id")
                port_data = {}
                if port_id:
                    p_get = supabase.table("portfolios").select("*").eq("id", port_id).execute()
                    if p_get.data:
                        port_data = p_get.data[0]
                c["portfolios"] = port_data

                is_sender = (str(c.get("talep_gonderen_id")).strip() == clean_user_id)
                c["is_sender"] = is_sender
                other_id = c.get("talep_alan_id") if is_sender else c.get("talep_gonderen_id")
                c["other_agent_id"] = other_id

                c["role_text"] = "Giden Teklif (Sizin Talebiniz)" if is_sender else "Gelen Teklif (Meslektaşınızdan)"
                c["other_agent"] = "Meslektaşınız"
                c["other_agent_avatar"] = None
                c["other_agent_phone"] = None

                if other_id:
                    u_get = supabase.table("users").select("id, ad_soyad, eposta, telefon, profil_foto, sirket_unvani").eq("id", other_id).execute()
                    if u_get.data:
                        c["other_agent"] = u_get.data[0].get("ad_soyad") or u_get.data[0].get("eposta")
                        c["other_agent_phone"] = u_get.data[0].get("telefon") or "Belirtilmemiş"
                        c["other_agent_avatar"] = u_get.data[0].get("profil_foto")

                collab_id_str = str(c.get("id")).strip()
                c["has_reviewed"] = (collab_id_str in reviewed_collab_ids)

                g_onay = bool(c.get("talep_gonderen_onay") or c.get("gonderen_onay"))
                a_onay = bool(c.get("talep_alan_onay") or c.get("alan_onay"))
                c["my_approval"] = g_onay if is_sender else a_onay
                c["other_approval"] = a_onay if is_sender else g_onay

                filtered_list.append(c)

    except Exception as e:
        filtered_list = []
        print(f"[İŞBİRLİKLERİM SORGU HATASI]: {e}")

    # Proje Tescilleri
    project_registrations = []
    try:
        p_reg_res = (
            supabase.table("project_customer_registrations")
            .select("*, projects(ad, ilce, partner_komisyon_orani, users:firma_id(sirket_unvani, ad_soyad))")
            .eq("agent_id", clean_user_id)
            .order("created_at", desc=True)
            .execute()
        )
        raw_regs = p_reg_res.data or []
        now = datetime.now(timezone.utc)

        for r in raw_regs:
            st = str(r.get("durum") or "").strip().lower()
            is_reg_match = False

            if tab == "aktif" and st in ["doğrulandı", "görüşmede", "yer gösterimi", "rezervasyon"]:
                is_reg_match = True
            elif tab == "bekleyen" and st in ["beklemede", "onay bekliyor"]:
                is_reg_match = True
            elif tab == "tamamlanan" and st in ["satış yapıldı", "satis yapildi", "iptal edildi", "reddedildi"]:
                is_reg_match = True

            if is_reg_match:
                end_date_str = r.get("koruma_bitis_tarihi")
                days_left = 90
                if end_date_str:
                    try:
                        clean_dt = end_date_str.replace("Z", "+00:00")
                        end_dt = datetime.fromisoformat(clean_dt)
                        days_left = max((end_dt - now).days, 0)
                    except Exception:
                        days_left = 90
                r["days_left"] = days_left
                project_registrations.append(r)

    except Exception as e:
        print(f"[PROJE TESCİLLERİ HATASI]: {e}")
        project_registrations = []

    return templates.TemplateResponse(
        request=request,
        name="collaborations/my_collaborations.html",
        context={
            "tab": tab,
            "subtab": subtab,
            "collaborations": filtered_list,
            "project_registrations": project_registrations,
            "user_id": clean_user_id
        }
    )

# ================= 2. İŞBİRLİĞİ DETAY SAYFASI =================
@router.get("/detail/{collab_id}", response_class=HTMLResponse)
def get_collaboration_detail(request: Request, collab_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        c_res = supabase.table("collaboration_requests").select("*").eq("id", collab_id).single().execute()
        collab = c_res.data or {}

        port_id = collab.get("ilgili_ilan_id")
        portfolio = {}
        if port_id:
            p_res = supabase.table("portfolios").select("*").eq("id", port_id).single().execute()
            portfolio = p_res.data or {}

        is_sender = (str(collab.get("talep_gonderen_id")).strip() == clean_user_id)
        other_id = collab.get("talep_alan_id") if is_sender else collab.get("talep_gonderen_id")

        other_user = {}
        if other_id:
            u_res = supabase.table("users").select("*").eq("id", other_id).single().execute()
            other_user = u_res.data or {}

        g_onay = bool(collab.get("talep_gonderen_onay") or collab.get("gonderen_onay"))
        a_onay = bool(collab.get("talep_alan_onay") or collab.get("alan_onay"))
        my_approval = g_onay if is_sender else a_onay
        other_approval = a_onay if is_sender else g_onay

    except Exception as e:
        print(f"[DETAY GETİRME HATASI]: {e}")
        return RedirectResponse(url="/collaborations/my", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="collaborations/detail.html",
        context={
            "collab": collab,
            "portfolio": portfolio,
            "other_user": other_user,
            "is_sender": is_sender,
            "my_approval": my_approval,
            "other_approval": other_approval
        }
    )

# ================= 3. TEKLİF GÖNDERME & YANITLAMA & ŞART DÜZENLEME =================
@router.post("/send")
def post_send_collaboration(
    ilgili_ilan_id: str = Form(...),
    target_owner_id: str = Form(...),
    isbirligi_kosulu: str = Form(...),
    talep_tipi: str = Form("İşbirliği Talebi"),
    notlar: str = Form(""),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_target_id = str(target_owner_id).strip()

    if is_relationship_blocked(clean_user_id, clean_target_id):
        return RedirectResponse(url="/dashboard?error=blocked", status_code=303)

    try:
        supabase.table("collaboration_requests").insert({
            "ilgili_ilan_id": ilgili_ilan_id,
            "talep_gonderen_id": clean_user_id,
            "talep_alan_id": clean_target_id,
            "talep_tipi": talep_tipi,
            "isbirligi_kosulu": isbirligi_kosulu.strip(),
            "durum": "Beklemede"
        }).execute()

        sender = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        s_name = sender.data.get("ad_soyad") if sender.data else "Bir meslektaşınız"

        # BİLDİRİM 1: Karşı tarafa yeni işbirliği teklifi bildirimi
        send_notification(
            user_id=clean_target_id,
            baslik="Yeni İşbirliği Teklifi 🤝",
            icerik=f"{s_name} adlı meslektaşınız portföyünüz için ({isbirligi_kosulu.strip()}) şartıyla işbirliği teklifi gönderdi.",
            hedef_url="/collaborations/my?tab=bekleyen"
        )
    except Exception as e:
        print(f"[TEKLİF İLETME HATASI]: {e}")

    return RedirectResponse(url="/collaborations/my?tab=bekleyen", status_code=303)

@router.post("/accept/{collab_id}")
def post_accept_collaboration(collab_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    try:
        c_res = supabase.table("collaboration_requests").select("talep_gonderen_id").eq("id", collab_id).single().execute()
        supabase.table("collaboration_requests").update({"durum": "Aktif"}).eq("id", collab_id).eq("talep_alan_id", clean_user_id).execute()

        user_info = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        acceptor_name = user_info.data.get("ad_soyad") if user_info.data else "Meslektaşınız"

        # BİLDİRİM 2: Teklifi gönderene kabul edildi bildirimi
        if c_res.data and c_res.data.get("talep_gonderen_id"):
            send_notification(
                user_id=c_res.data.get("talep_gonderen_id"),
                baslik="İşbirliği Teklifiniz Kabul Edildi! 🎉",
                icerik=f"{acceptor_name} adlı meslektaşınız işbirliği teklifinizi kabul etti. Artık birlikte satış yürütebilirsiniz.",
                hedef_url=f"/collaborations/detail/{collab_id}"
            )
    except Exception as e:
        print(f"[KABUL HATASI]: {e}")

    return RedirectResponse(url="/collaborations/my?tab=aktif", status_code=303)

@router.post("/reject/{collab_id}")
def post_reject_collaboration(collab_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    try:
        c_res = supabase.table("collaboration_requests").select("talep_gonderen_id").eq("id", collab_id).single().execute()
        supabase.table("collaboration_requests").update({"durum": "Reddedildi"}).eq("id", collab_id).eq("talep_alan_id", clean_user_id).execute()

        user_info = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        rejector_name = user_info.data.get("ad_soyad") if user_info.data else "Meslektaşınız"

        # BİLDİRİM 3: Teklifi gönderene ret bildirimi
        if c_res.data and c_res.data.get("talep_gonderen_id"):
            send_notification(
                user_id=c_res.data.get("talep_gonderen_id"),
                baslik="İşbirliği Teklifi Reddedildi",
                icerik=f"{rejector_name} adlı meslektaşınız işbirliği teklifinizi reddetti.",
                hedef_url="/collaborations/my?tab=tamamlanan"
            )
    except Exception as e:
        print(f"[REDDETME HATASI]: {e}")

    return RedirectResponse(url="/collaborations/my?tab=tamamlanan", status_code=303)

@router.post("/cancel/{collab_id}")
def post_cancel_collaboration(collab_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    try:
        c_res = supabase.table("collaboration_requests").select("talep_alan_id").eq("id", collab_id).single().execute()
        supabase.table("collaboration_requests").update({"durum": "İptal Edildi"}).eq("id", collab_id).eq("talep_gonderen_id", clean_user_id).execute()

        user_info = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        canceler_name = user_info.data.get("ad_soyad") if user_info.data else "Meslektaşınız"

        # BİLDİRİM 4: Teklifi alan tarafa iptal bildirimi
        if c_res.data and c_res.data.get("talep_alan_id"):
            send_notification(
                user_id=c_res.data.get("talep_alan_id"),
                baslik="İşbirliği Teklifi İptal Edildi",
                icerik=f"{canceler_name} adlı meslektaşınız göndermiş olduğu işbirliği teklifini geri çekti / iptal etti.",
                hedef_url="/collaborations/my?tab=tamamlanan"
            )
    except Exception as e:
        print(f"[İPTAL HATASI]: {e}")

    return RedirectResponse(url="/collaborations/my?tab=tamamlanan", status_code=303)

@router.post("/update-terms/{collab_id}")
def post_update_terms(collab_id: str, isbirligi_kosulu: str = Form(...), user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    new_terms = isbirligi_kosulu.strip()

    try:
        c_res = supabase.table("collaboration_requests").select("talep_alan_id").eq("id", collab_id).single().execute()
        supabase.table("collaboration_requests").update({"isbirligi_kosulu": new_terms}).eq("id", collab_id).eq("talep_gonderen_id", clean_user_id).execute()

        user_info = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        updater_name = user_info.data.get("ad_soyad") if user_info.data else "Meslektaşınız"

        # BİLDİRİM 5: Karşı tarafa şart güncelleme bildirimi
        if c_res.data and c_res.data.get("talep_alan_id"):
            send_notification(
                user_id=c_res.data.get("talep_alan_id"),
                baslik="İşbirliği Şartı Güncellendi ✏️",
                icerik=f"{updater_name} adlı meslektaşınız işbirliği şartını '{new_terms}' olarak güncelledi.",
                hedef_url="/collaborations/my?tab=bekleyen"
            )
    except Exception as e:
        print(f"[ŞART GÜNCELLEME HATASI]: {e}")

    return RedirectResponse(url="/collaborations/my?tab=bekleyen", status_code=303)

# ================= 4. ÇİFT TARAFLI SATIŞ KAPATMA ONAYI =================
@router.post("/approve-success/{collab_id}")
def post_approve_success(collab_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_collab_id = str(collab_id).strip()

    try:
        c_res = supabase.table("collaboration_requests").select("*").eq("id", clean_collab_id).single().execute()
        collab = c_res.data
        if not collab:
            return RedirectResponse(url="/collaborations/my", status_code=303)

        is_sender = (str(collab.get("talep_gonderen_id")).strip() == clean_user_id)
        other_approved = bool(
            (collab.get("talep_alan_onay") or collab.get("alan_onay"))
            if is_sender
            else (collab.get("talep_gonderen_onay") or collab.get("gonderen_onay"))
        )
        other_id = str(collab.get("talep_alan_id") if is_sender else collab.get("talep_gonderen_id")).strip()

        user_info = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        my_name = user_info.data.get("ad_soyad") if user_info.data else "Meslektaşınız"

        update_payload = {}
        if is_sender:
            update_payload["talep_gonderen_onay"] = True
            update_payload["gonderen_onay"] = True
        else:
            update_payload["talep_alan_onay"] = True
            update_payload["alan_onay"] = True

        if other_approved:
            update_payload["durum"] = "Tamamlandı"
            update_payload["kapatma_sebebi"] = "Başarılı Satış"
            
            port_id = collab.get("ilgili_ilan_id")
            if port_id:
                try:
                    supabase.table("portfolios").update({"durum": "Satıldı", "isbirliğine_acik": False}).eq("id", port_id).execute()
                except Exception as port_err:
                    print(f"[PORTFÖY KİLİTLEME HATASI]: {port_err}")

            # BİLDİRİM 6: İşlem tamamlandığında iki tarafa teyit
            send_notification(
                user_id=clean_user_id,
                baslik="Satış Başarıyla Kapatıldı! 🏆",
                icerik="Her iki tarafın teyidiyle ortak satış tamamlandı. Meslektaşınızı puanlayabilirsiniz.",
                hedef_url=f"/collaborations/review/{clean_collab_id}"
            )
            send_notification(
                user_id=other_id,
                baslik="Satış Başarıyla Kapatıldı! 🏆",
                icerik=f"{my_name} adlı meslektaşınızın da teyidiyle ortak satışınız başarıyla tamamlandı. Puanlama yapabilirsiniz.",
                hedef_url=f"/collaborations/review/{clean_collab_id}"
            )

        else:
            update_payload["durum"] = "basari_onayi_bekleniyor"
            # BİLDİRİM 7: Diğer tarafa onay bekleme çağrısı
            send_notification(
                user_id=other_id,
                baslik="Satış Kapatma Onayınız Bekleniyor ⏳",
                icerik=f"{my_name} adlı meslektaşınız satışı başarıyla tamamlandı olarak işaretledi. Lütfen işbirliği detayından onayınızı verin.",
                hedef_url=f"/collaborations/detail/{clean_collab_id}"
            )

        supabase.table("collaboration_requests").update(update_payload).eq("id", clean_collab_id).execute()

    except Exception as e:
        print(f"[BAŞARI ONAY KRİTİK HATA]: {e}")

    return RedirectResponse(url=f"/collaborations/detail/{clean_collab_id}", status_code=303)

# ================= 5. BAŞARISIZ OLARAK KAPATMA =================
@router.post("/close-failed/{collab_id}")
def post_close_failed(collab_id: str, sebep: str = Form("Anlaşma Sağlanamadı"), user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        c_res = supabase.table("collaboration_requests").select("talep_gonderen_id, talep_alan_id").eq("id", collab_id).single().execute()
        if c_res.data:
            other_id = c_res.data["talep_alan_id"] if c_res.data["talep_gonderen_id"] == clean_user_id else c_res.data["talep_gonderen_id"]
            user_info = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
            my_name = user_info.data.get("ad_soyad") if user_info.data else "Meslektaşınız"

            # BİLDİRİM 8: Süreç başarısız kapatıldığında karşı tarafa haber verme
            send_notification(
                user_id=other_id,
                baslik="İşbirliği Süreci Sonlandırıldı",
                icerik=f"{my_name} ile olan işbirliği süreci sonlandırıldı. Sebep: {sebep.strip()}.",
                hedef_url="/collaborations/my?tab=tamamlanan"
            )

        supabase.table("collaboration_requests").update({
            "durum": "Başarısız",
            "kapatma_sebebi": sebep.strip()
        }).eq("id", collab_id).execute()
    except Exception as e:
        print(f"[BAŞARISIZ KAPATMA HATASI]: {e}")

    return RedirectResponse(url="/collaborations/my?tab=tamamlanan", status_code=303)

# ================= 6. PUAN & YORUM =================
@router.get("/review/{collab_id}", response_class=HTMLResponse)
def get_review_form(request: Request, collab_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_collab_id = str(collab_id).strip()

    try:
        already = (
            supabase.table("agent_reviews")
            .select("id")
            .eq("collaboration_id", clean_collab_id)
            .eq("reviewer_id", clean_user_id)
            .execute()
        )
        if already.data and len(already.data) > 0:
            return RedirectResponse(url="/collaborations/my?tab=tamamlanan", status_code=303)

        c_res = supabase.table("collaboration_requests").select("*").eq("id", clean_collab_id).single().execute()
        collab = c_res.data or {}

        target_id = collab.get("talep_alan_id") if str(collab.get("talep_gonderen_id")).strip() == clean_user_id else collab.get("talep_gonderen_id")
        target_name = "Meslektaşınız"
        if target_id:
            u_res = supabase.table("users").select("ad_soyad").eq("id", target_id).single().execute()
            if u_res.data and u_res.data.get("ad_soyad"):
                target_name = u_res.data.get("ad_soyad")
    except Exception as e:
        print(f"[REVIEW FORM HATASI]: {e}")
        return RedirectResponse(url="/collaborations/my?tab=tamamlanan", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="collaborations/reviews.html",
        context={
            "collab": collab,
            "target_id": target_id,
            "target_name": target_name
        }
    )

@router.post("/review")
def post_submit_review(
    request: Request,
    collab_id: str = Form(...),
    target_id: str = Form(...),
    puan: int = Form(...),
    yorum: str = Form(""),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_target_id = str(target_id).strip()
    clean_collab_id = str(collab_id).strip()

    try:
        chk = (
            supabase.table("agent_reviews")
            .select("id")
            .eq("collaboration_id", clean_collab_id)
            .eq("reviewer_id", clean_user_id)
            .execute()
        )
        if not chk.data or len(chk.data) == 0:
            review_data = {
                "collaboration_id": clean_collab_id,
                "reviewer_id": clean_user_id,
                "target_agent_id": clean_target_id,
                "puan": int(puan),
                "yorum": (yorum or "").strip()
            }
            supabase.table("agent_reviews").insert(review_data).execute()

            u_info = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
            r_name = u_info.data.get("ad_soyad") if u_info.data else "Bir meslektaşınız"

            send_notification(
                user_id=clean_target_id,
                baslik="Yeni Değerlendirme Aldınız ⭐",
                icerik=f"{r_name} adlı meslektaşınız tamamlanan ortak satışınız için size {puan} yıldız verdi.",
                hedef_url="/profile"
            )
    except Exception as e:
        print(f"[PUANLAMA KAYDETME HATASI]: {e}")

    return RedirectResponse(url="/collaborations/my?tab=tamamlanan", status_code=303)