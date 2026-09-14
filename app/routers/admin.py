from fastapi import APIRouter, Request, Form, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.notifier import send_notification

router = APIRouter(prefix="/admin", tags=["Admin"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def is_admin(user_id: str) -> bool:
    if not user_id:
        return False
    try:
        u = supabase.table("users").select("rol").eq("id", user_id).single().execute()
        return bool(u.data and u.data.get("rol") == "admin")
    except Exception:
        return False

# ================= 1. ADMIN GİRİŞ SAYFASI =================
@router.get("/login", response_class=HTMLResponse)
def get_admin_login(request: Request):
    return templates.TemplateResponse(request=request, name="admin/login.html")

@router.post("/login")
def post_admin_login(
    request: Request,
    response: Response,
    eposta: str = Form(...),
    sifre: str = Form(...)
):
    try:
        res = supabase.table("users").select("*").eq("eposta", eposta.strip().lower()).execute()
        if not res.data:
            return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": "Admin kullanıcısı bulunamadı."})

        user = res.data[0]
        if user.get("sifre") != sifre:
            return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": "Hatalı yönetici şifresi."})

        if user.get("rol") != "admin":
            return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": "Bu hesaba ait yönetici yetkisi yok!"})

        redirect = RedirectResponse(url="/admin/dashboard", status_code=303)
        redirect.set_cookie(key="user_id", value=str(user["id"]), max_age=86400 * 30, httponly=True)
        return redirect

    except Exception as e:
        return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": f"Giriş hatası: {str(e)}"})

# ================= 2. ADMIN ANA KONSOLU =================
@router.get("/dashboard", response_class=HTMLResponse)
def get_admin_dashboard(request: Request, tab: str = "onaylar", member_type: str = "agent", user_id: str = Cookie(None)):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        # 1. Onay Bekleyenler (Emlakçılar ve Firmalar)
        p_res = supabase.table("users").select("*").eq("durum", "onay_bekliyor").order("created_at", desc=True).execute()
        pending_users = p_res.data or []

        # 2. Tüm Üyeler (Admin hariç)
        u_res = supabase.table("users").select("*").neq("rol", "admin").order("created_at", desc=True).execute()
        all_raw_users = u_res.data or []

        # Emlakçılar ve Firmalar ayrımı
        agents = []
        companies = []
        for u in all_raw_users:
            ft = str(u.get("firma_tipi") or "").lower()
            if ft in ["sirket", "proje_firmasi", "developer"]:
                companies.append(u)
            else:
                agents.append(u)

        # 3. Destek Talepleri
        tick_res = supabase.table("support_tickets").select("*, sender:user_id(ad_soyad, eposta, telefon, sirket_unvani, firma_tipi)").order("created_at", desc=True).execute()
        tickets = tick_res.data or []

    except Exception as e:
        print(f"[ADMIN VERİ GETİRME HATASI]: {e}")
        pending_users, agents, companies, tickets = [], [], [], []

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "tab": tab,
            "member_type": member_type,
            "pending_users": pending_users,
            "agents": agents,
            "companies": companies,
            "tickets": tickets
        }
    )

# ================= 3. TEK BİR ÜYENİN TÜM DETAYLARINI GETİREN API =================
@router.get("/api/user-detail/{target_id}")
def api_get_user_detail(target_id: str, user_id: str = Cookie(None)):
    if not user_id or not is_admin(user_id):
        return JSONResponse({"error": "Yetkisiz işlem"}, status_code=403)

    clean_target_id = str(target_id).strip()

    try:
        # Kullanıcı ana bilgisi
        u_res = supabase.table("users").select("*").eq("id", clean_target_id).single().execute()
        target_user = u_res.data
        if not target_user:
            return JSONResponse({"error": "Kullanıcı bulunamadı"}, status_code=404)

        is_company = str(target_user.get("firma_tipi") or "").lower() in ["sirket", "proje_firmasi", "developer"]
        
        detail_data = {
            "user": target_user,
            "is_company": is_company,
            "invited_by": None,
            "portfolios": [],
            "collaborations": [],
            "projects": [],
            "project_sales": []
        }

        if not is_company:
            # 1. Kim Davet Etti? (invitation_codes üzerinden arama)
            try:
                inv_res = supabase.table("invitation_codes").select("olusturan_id, users:olusturan_id(ad_soyad, eposta, telefon, sirket_unvani)").eq("kullanan_id", clean_target_id).execute()
                if inv_res.data and len(inv_res.data) > 0 and inv_res.data[0].get("users"):
                    detail_data["invited_by"] = inv_res.data[0]["users"]
            except Exception:
                detail_data["invited_by"] = None

            # 2. Portföyleri
            p_res = supabase.table("portfolios").select("*").eq("porfoy_sahibi_id", clean_target_id).order("created_at", desc=True).execute()
            detail_data["portfolios"] = p_res.data or []

            # 3. Yaptığı İşbirlikleri
            c_res = supabase.table("collaboration_requests").select(
                "*, portfolios:ilgili_ilan_id(gayrimenkul_tipi, ilce, fiyat)"
            ).or_(f"talep_gonderen_id.eq.{clean_target_id},talep_alan_id.eq.{clean_target_id}").order("created_at", desc=True).execute()
            detail_data["collaborations"] = c_res.data or []

        else:
            # Şirket / Proje Firması ise:
            # 1. Projeleri
            prj_res = supabase.table("projects").select("*").eq("firma_id", clean_target_id).order("created_at", desc=True).execute()
            all_projects = prj_res.data or []
            detail_data["projects"] = all_projects

            # 2. Hangi emlakçıyla hangi tescil/satışı yapmış?
            p_ids = [p["id"] for p in all_projects]
            if p_ids:
                reg_res = supabase.table("project_customer_registrations").select(
                    "*, projects(ad, partner_komisyon_orani), users:agent_id(ad_soyad, telefon, eposta, sirket_unvani)"
                ).in_("project_id", p_ids).order("created_at", desc=True).execute()
                detail_data["project_sales"] = reg_res.data or []

        return JSONResponse({"success": True, "data": detail_data})

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ================= 4. ÜYELİK ONAY & RED =================
@router.post("/users/approve/{target_id}")
def post_approve_user(target_id: str, user_id: str = Cookie(None)):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        supabase.table("users").update({"durum": "aktif", "belge_onayli": True}).eq("id", target_id).execute()
    except Exception as e:
        print(f"[ONAY HATA]: {e}")
    return RedirectResponse(url="/admin/dashboard?tab=onaylar", status_code=303)

@router.post("/users/reject/{target_id}")
def post_reject_user(target_id: str, user_id: str = Cookie(None)):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        supabase.table("users").update({"durum": "reddedildi", "belge_onayli": False}).eq("id", target_id).execute()
    except Exception as e:
        print(f"[RED HATA]: {e}")
    return RedirectResponse(url="/admin/dashboard?tab=onaylar", status_code=303)

# ================= 5. DESTEK BİLETİNİ GÜNCELLE =================
@router.post("/tickets/update-status/{ticket_id}")
def post_update_ticket_status(ticket_id: str, durum: str = Form(...), user_id: str = Cookie(None)):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        t_res = supabase.table("support_tickets").select("user_id, konu").eq("id", ticket_id).single().execute()
        supabase.table("support_tickets").update({"durum": durum}).eq("id", ticket_id).execute()

        if t_res.data:
            target_user_id = t_res.data.get("user_id")
            konu = t_res.data.get("konu")
            send_notification(
                user_id=target_user_id,
                baslik=f"Destek Talebiniz Güncellendi ({durum.upper()})",
                icerik=f"'{konu}' başlıklı talebinizin yeni durumu: {durum}.",
                hedef_url="/settings"
            )
    except Exception as e:
        print(f"[BİLET GÜNCELLEME HATASI]: {e}")

    return RedirectResponse(url="/admin/dashboard?tab=destek", status_code=303)

# ================= 6. ÜYE DURAKLATMA (ASKIYA ALMA) =================
@router.post("/users/toggle-pause/{target_id}")
def post_pause_user(
    target_id: str,
    confirm_email: str = Form(...),
    target_email: str = Form(...),
    user_id: str = Cookie(None)
):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    if confirm_email.strip().lower() != target_email.strip().lower():
        return RedirectResponse(url="/admin/dashboard?tab=uyeler&error=email_mismatch", status_code=303)

    try:
        u = supabase.table("users").select("durum").eq("id", target_id).single().execute()
        if u.data:
            current = u.data.get("durum")
            new_status = "aktif" if current == "askida" else "askida"
            supabase.table("users").update({"durum": new_status}).eq("id", target_id).execute()
    except Exception as e:
        print(f"[DURAKLATMA HATA]: {e}")

    return RedirectResponse(url="/admin/dashboard?tab=uyeler", status_code=303)

# ================= 7. ÜYE KESİN SİLME =================
@router.post("/users/hard-delete/{target_id}")
def post_delete_user(
    target_id: str,
    confirm_email: str = Form(...),
    target_email: str = Form(...),
    user_id: str = Cookie(None)
):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    if confirm_email.strip().lower() != target_email.strip().lower():
        return RedirectResponse(url="/admin/dashboard?tab=uyeler&error=email_mismatch", status_code=303)

    try:
        supabase.table("users").delete().eq("id", target_id).execute()
    except Exception as e:
        print(f"[ÜYE SİLME HATA]: {e}")

    return RedirectResponse(url="/admin/dashboard?tab=uyeler", status_code=303)