from fastapi import APIRouter, Request, Form, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.notifier import send_notification

router = APIRouter(prefix="/settings", tags=["Settings"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ================= 1. AYARLAR ANA SAYFASI =================
@router.get("", response_class=HTMLResponse)
def get_settings(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        u_res = supabase.table("users").select("*").eq("id", clean_user_id).single().execute()
        user = u_res.data or {}

        s_res = supabase.table("user_settings").select("*").eq("user_id", clean_user_id).execute()
        if s_res.data and len(s_res.data) > 0:
            settings = s_res.data[0]
        else:
            default_settings = {
                "user_id": clean_user_id,
                "notify_collab": True,
                "notify_referral": True,
                "notify_messages": True,
                "notify_sales": True
            }
            try:
                ins = supabase.table("user_settings").insert(default_settings).execute()
                settings = ins.data[0] if ins.data else default_settings
            except Exception:
                settings = default_settings

        t_res = supabase.table("support_tickets").select("*").eq("user_id", clean_user_id).order("created_at", desc=True).execute()
        tickets = t_res.data or []

    except Exception as e:
        print(f"[AYARLAR VERİ GETİRME HATASI]: {e}")
        user, settings, tickets = {}, {}, []

    return templates.TemplateResponse(
        request=request,
        name="settings/index.html",
        context={
            "user": user,
            "settings": settings,
            "tickets": tickets,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err")
        }
    )

# ================= 2. BİLDİRİM TERCİHLERİNİ GÜNCELLE =================
@router.post("/notifications")
def post_update_notifications(
    notify_collab: str = Form(None),
    notify_referral: str = Form(None),
    notify_messages: str = Form(None),
    notify_sales: str = Form(None),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    payload = {
        "user_id": clean_user_id,
        "notify_collab": bool(notify_collab),
        "notify_referral": bool(notify_referral),
        "notify_messages": bool(notify_messages),
        "notify_sales": bool(notify_sales)
    }

    try:
        chk = supabase.table("user_settings").select("user_id").eq("user_id", clean_user_id).execute()
        
        if chk.data and len(chk.data) > 0:
            supabase.table("user_settings").update({
                "notify_collab": payload["notify_collab"],
                "notify_referral": payload["notify_referral"],
                "notify_messages": payload["notify_messages"],
                "notify_sales": payload["notify_sales"]
            }).eq("user_id", clean_user_id).execute()
        else:
            supabase.table("user_settings").insert(payload).execute()

    except Exception as e:
        err_msg = str(e).replace(" ", "_")[:50]
        print(f"\n[!!! GERÇEK BİLDİRİM HATASI !!!]: {e}\n")
        return RedirectResponse(url=f"/settings?err={err_msg}", status_code=303)

    return RedirectResponse(url="/settings?msg=notify_updated", status_code=303)

# ================= 3. İLETİŞİM BİLGİLERİNİ GÜNCELLE =================
@router.post("/contact")
def post_update_contact(
    telefon: str = Form(...),
    sirket_unvani: str = Form(None),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    try:
        supabase.table("users").update({
            "telefon": telefon.strip(),
            "sirket_unvani": sirket_unvani.strip() if sirket_unvani else None
        }).eq("id", clean_user_id).execute()
    except Exception as e:
        print(f"[İLETİŞİM GÜNCELLEME HATASI]: {e}")
        return RedirectResponse(url="/settings?err=contact_failed", status_code=303)

    return RedirectResponse(url="/settings?msg=contact_updated", status_code=303)

# ================= 4. ŞİFRE DEĞİŞTİRME =================
@router.post("/change-password")
def post_change_password(
    eski_sifre: str = Form(...),
    yeni_sifre: str = Form(...),
    yeni_sifre_tekrar: str = Form(...),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    if yeni_sifre != yeni_sifre_tekrar:
        return RedirectResponse(url="/settings?err=pass_mismatch", status_code=303)

    try:
        u_res = supabase.table("users").select("sifre").eq("id", clean_user_id).single().execute()
        if not u_res.data or u_res.data.get("sifre") != eski_sifre:
            return RedirectResponse(url="/settings?err=wrong_old_pass", status_code=303)

        supabase.table("users").update({"sifre": yeni_sifre}).eq("id", clean_user_id).execute()
    except Exception as e:
        print(f"[ŞİFRE DEĞİŞTİRME HATASI]: {e}")
        return RedirectResponse(url="/settings?err=pass_failed", status_code=303)

    return RedirectResponse(url="/settings?msg=pass_updated", status_code=303)

# ================= 5. DESTEK & ŞİKAYET BİLDİR =================
@router.post("/support")
def post_send_support(
    konu: str = Form(...),
    mesaj: str = Form(...),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    msg_clean = mesaj.strip()

    if not msg_clean:
        return RedirectResponse(url="/settings?err=empty_support", status_code=303)

    try:
        supabase.table("support_tickets").insert({
            "user_id": clean_user_id,
            "konu": konu.strip(),
            "mesaj": msg_clean,
            "durum": "beklemede"
        }).execute()

        admins = supabase.table("users").select("id").eq("rol", "admin").execute()
        for adm in (admins.data or []):
            send_notification(
                user_id=adm["id"],
                baslik="Yeni Destek / Şikayet Bildirimi 📩",
                icerik=f"{konu.strip()}: {msg_clean[:40]}...",
                hedef_url="/admin/dashboard?tab=destek"
            )
    except Exception as e:
        print(f"[DESTEK TALEBİ OLUŞTURMA HATASI]: {e}")
        return RedirectResponse(url="/settings?err=support_failed", status_code=303)

    return RedirectResponse(url="/settings?msg=support_sent", status_code=303)

# ================= 6. HESABI DONDUR (ASKIYA AL) =================
@router.post("/freeze-account")
def post_freeze_account(user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        supabase.table("users").update({"durum": "askida"}).eq("id", clean_user_id).execute()
        supabase.table("portfolios").update({"durum": "Pasif"}).eq("porfoy_sahibi_id", clean_user_id).execute()
    except Exception as e:
        print(f"[HESAP DONDURMA HATASI]: {e}")
        return RedirectResponse(url="/settings?err=freeze_failed", status_code=303)

    res = RedirectResponse(url="/login", status_code=303)
    res.delete_cookie(key="user_id")
    return res

# ================= 7. HESABI KALICI OLARAK SİL =================
@router.post("/delete-account")
def post_delete_account(
    confirm_text: str = Form(...),
    sifre: str = Form(...),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    if confirm_text.strip().upper() != "HESABIMI SİL":
        return RedirectResponse(url="/settings?err=delete_confirm_failed", status_code=303)

    try:
        u_res = supabase.table("users").select("sifre").eq("id", clean_user_id).single().execute()
        if not u_res.data or u_res.data.get("sifre") != sifre:
            return RedirectResponse(url="/settings?err=delete_wrong_pass", status_code=303)

        supabase.table("users").delete().eq("id", clean_user_id).execute()
    except Exception as e:
        print(f"[HESAP SİLME HATASI]: {e}")
        return RedirectResponse(url="/settings?err=delete_failed", status_code=303)

    res = RedirectResponse(url="/login", status_code=303)
    res.delete_cookie(key="user_id")
    return res