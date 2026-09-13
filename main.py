from fastapi import FastAPI, Request, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path

from app.database import supabase
from app.routers import (
    auth,
    portfolios,
    demands,
    requests as user_requests,
    collaborations,
    network,
    messages,
    profile,
    settings,
    admin,
    notifications,
    company,
    project_network
)

app = FastAPI(title="EMLAKMATCH", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent

static_dir = BASE_DIR / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

# Router Bağlantıları
app.include_router(auth.router)
app.include_router(portfolios.router)
app.include_router(demands.router)
app.include_router(user_requests.router)
app.include_router(collaborations.router)
app.include_router(network.router)
app.include_router(messages.router)
app.include_router(profile.router)
app.include_router(settings.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(company.router)
app.include_router(project_network.router)

# Dashboard
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    user_name = "Emlak Profesyoneli"
    active_count = 0
    pending_count = 0
    completed_count = 0
    unread_notifications = 0

    try:
        u_res = supabase.table("users").select("ad_soyad, firma_tipi").eq("id", clean_user_id).single().execute()
        if u_res.data:
            if str(u_res.data.get("firma_tipi") or "").lower() in ["sirket", "proje_firmasi", "developer"]:
                return RedirectResponse(url="/company/dashboard", status_code=303)
            if u_res.data.get("ad_soyad"):
                user_name = u_res.data.get("ad_soyad")

        collabs = supabase.table("collaboration_requests").select("durum").or_(
            f"talep_gonderen_id.eq.{clean_user_id},talep_alan_id.eq.{clean_user_id}"
        ).execute().data or []

        for c in collabs:
            st = str(c.get("durum") or "").strip().lower()
            if st in ["aktif", "basari_onayi_bekleniyor"]:
                active_count += 1
            elif st in ["beklemede", "bekleyen"]:
                pending_count += 1
            elif st in ["tamamlandı", "reddedildi", "iptal edildi", "başarısız"]:
                completed_count += 1

        # GARANTİLİ VE ŞEMA ESNEK OKUNMAMIŞ BİLDİRİM SAYIMI
        try:
            notif_res = supabase.table("notifications").select("*").eq("user_id", clean_user_id).execute()
            user_notifs = notif_res.data or []
            
            # Hem 'okundu_mu' hem de 'okundu' alanlarını kontrol eder
            unread_notifications = len([
                n for n in user_notifs 
                if (not n.get("okundu_mu", False) if "okundu_mu" in n else not n.get("okundu", False))
            ])
            print(f"[DASHBOARD SAYAÇ]: Kullanıcı ({clean_user_id}) için {unread_notifications} okunmamış bildirim bulundu.")
        except Exception as n_err:
            print(f"[DASHBOARD BİLDİRİM SAYIM HATASI]: {n_err}")
            unread_notifications = 0

    except Exception as e:
        print(f"[DASHBOARD HATASI]: {e}")

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "user_name": user_name,
            "active_count": active_count,
            "pending_count": pending_count,
            "completed_count": completed_count,
            "unread_notifications": unread_notifications
        }
    )

@app.get("/")
def root_redirect():
    return RedirectResponse(url="/dashboard", status_code=303)