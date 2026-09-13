from fastapi import APIRouter, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase

router = APIRouter(prefix="/notifications", tags=["Notifications"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ================= 1. BİLDİRİMLER SAYFASI =================
@router.get("", response_class=HTMLResponse)
def get_notifications(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    notifications = []

    try:
        res = supabase.table("notifications").select("*")\
            .eq("user_id", clean_user_id)\
            .order("created_at", desc=True)\
            .execute()
        notifications = res.data or []
    except Exception as e:
        notifications = []
        print(f"[BİLDİRİM LİSTELEME HATASI]: {e}")

    return templates.TemplateResponse(
        request=request,
        name="notifications/index.html",
        context={"notifications": notifications}
    )

# ================= 2. CANLI OKUNMAMIŞ BİLDİRİM SAYISI API =================
@router.get("/api/unread-count")
def get_unread_notification_count(user_id: str = Cookie(None)):
    if not user_id:
        return JSONResponse({"unread_count": 0})

    clean_user_id = str(user_id).strip()

    try:
        res = supabase.table("notifications").select("*").eq("user_id", clean_user_id).execute()
        all_notifs = res.data or []
        
        unread_count = 0
        for n in all_notifs:
            val = n.get("okundu_mu") if "okundu_mu" in n else n.get("okundu")
            if val is False or val == 0 or val is None:
                unread_count += 1

        return JSONResponse({"unread_count": unread_count})
    except Exception as e:
        print(f"[UNREAD SAYIM HATASI]: {e}")
        return JSONResponse({"unread_count": 0})

# ================= 3. TÜMÜNÜ OKUNDU İŞARETLE API =================
@router.post("/api/read-all")
def mark_all_notifications_read(user_id: str = Cookie(None)):
    if not user_id:
        return JSONResponse({"success": False}, status_code=401)

    clean_user_id = str(user_id).strip()

    try:
        try:
            supabase.table("notifications").update({"okundu_mu": True}).eq("user_id", clean_user_id).execute()
        except Exception:
            supabase.table("notifications").update({"okundu": True}).eq("user_id", clean_user_id).execute()
            
        return JSONResponse({"success": True})
    except Exception as e:
        print(f"[TÜMÜNÜ OKUNDU İŞARETLEME HATASI]: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)