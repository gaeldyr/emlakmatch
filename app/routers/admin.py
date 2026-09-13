from fastapi import APIRouter, Request, Form, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
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
def get_admin_dashboard(request: Request, tab: str = "onaylar", user_id: str = Cookie(None)):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        # 1. Onay Bekleyen Emlakçılar
        p_res = supabase.table("users").select("*").eq("durum", "onay_bekliyor").order("created_at", desc=True).execute()
        pending_users = p_res.data or []

        # 2. Tüm Üyeler
        u_res = supabase.table("users").select("*").neq("rol", "admin").order("created_at", desc=True).execute()
        all_users = u_res.data or []

        # 3. Tüm Portföyler
        port_res = supabase.table("portfolios").select("*, users:porfoy_sahibi_id(ad_soyad, eposta, telefon)").order("created_at", desc=True).execute()
        all_portfolios = port_res.data or []

        # 4. Destek & Şikayet Talepleri
        tick_res = supabase.table("support_tickets").select("*, sender:user_id(ad_soyad, eposta, telefon, sirket_unvani)").order("created_at", desc=True).execute()
        tickets = tick_res.data or []

        # 5. Onay Bekleyen Gruplar
        g_res = supabase.table("groups").select("*, kurucu:kurucu_id(ad_soyad, eposta, telefon, sirket_unvani)").eq("durum", "onay_bekliyor").order("created_at", desc=True).execute()
        pending_groups = g_res.data or []

    except Exception as e:
        print(f"[ADMIN VERİ GETİRME HATASI]: {e}")
        pending_users, all_users, all_portfolios, tickets, pending_groups = [], [], [], [], []

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "tab": tab,
            "pending_users": pending_users,
            "all_users": all_users,
            "all_portfolios": all_portfolios,
            "tickets": tickets,
            "pending_groups": pending_groups
        }
    )

# ================= 3. ÜYELİK ONAY & RED =================
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

# ================= 4. DESTEK / BİLDİRİM BİLETİNİ GÜNCELLE =================
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
                icerik=f"'{konu}' başlıklı destek talebinizin durumu: {durum}.",
                hedef_url="/settings"
            )
    except Exception as e:
        print(f"[BİLET GÜNCELLEME HATASI]: {e}")

    return RedirectResponse(url="/admin/dashboard?tab=destek", status_code=303)

# ================= 5. ÜYE DURAKLATMA =================
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

# ================= 6. ÜYE KESİN SİLME =================
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

# ================= 7. GRUP ONAY & RED =================
@router.post("/groups/approve/{group_id}")
def post_approve_group(group_id: str, user_id: str = Cookie(None)):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        # 1. Grubu aktif yap
        g_res = supabase.table("groups").select("kurucu_id, ad").eq("id", group_id).single().execute()
        supabase.table("groups").update({"durum": "aktif"}).eq("id", group_id).execute()

        # 2. Kurucuyu gruba 'admin' rolüyle üye yap
        if g_res.data and g_res.data.get("kurucu_id"):
            kurucu_id = g_res.data.get("kurucu_id")
            supabase.table("group_members").upsert({
                "group_id": group_id,
                "user_id": kurucu_id,
                "rol": "admin"
            }).execute()

            send_notification(
                user_id=kurucu_id,
                baslik="Grup Başvurunuz Onaylandı! 🎉",
                icerik=f"'{g_res.data.get('ad')}' adlı grup onaylandı ve yayına alındı. Artık yönetebilirsiniz.",
                hedef_url=f"/network/groups/{group_id}"
            )
    except Exception as e:
        print(f"[GRUP ONAY HATASI]: {e}")

    return RedirectResponse(url="/admin/dashboard?tab=grup_onaylari", status_code=303)

@router.post("/groups/reject/{group_id}")
def post_reject_group(group_id: str, user_id: str = Cookie(None)):
    if not user_id or not is_admin(user_id):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        g_res = supabase.table("groups").select("kurucu_id, ad").eq("id", group_id).single().execute()
        supabase.table("groups").update({"durum": "reddedildi"}).eq("id", group_id).execute()

        if g_res.data and g_res.data.get("kurucu_id"):
            send_notification(
                user_id=g_res.data.get("kurucu_id"),
                baslik="Grup Başvurunuz Reddedildi",
                icerik=f"'{g_res.data.get('ad')}' adlı grup başvurunuz platform kuralları gereği onaylanmadı.",
                hedef_url="/network?tab=gruplar"
            )
    except Exception as e:
        print(f"[GRUP RET HATASI]: {e}")

    return RedirectResponse(url="/admin/dashboard?tab=grup_onaylari", status_code=303)