import secrets
import string
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.notifier import send_notification

router = APIRouter(prefix="/projects", tags=["Project Network"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def generate_tescil_no():
    digits = ''.join(secrets.choice(string.digits) for _ in range(6))
    return f"TSC-{digits}"

def mask_phone_number(phone: str) -> str:
    cleaned = "".join([c for c in phone if c.isdigit()])
    if len(cleaned) >= 10:
        prefix = cleaned[:4]
        suffix = cleaned[-2:]
        return f"{prefix} XXX XX {suffix}"
    return "05XX XXX XX XX"

# ================= 1. PROJE AĞI (TÜM PROJELER) =================
@router.get("", response_class=HTMLResponse)
def get_projects_catalog(request: Request, user_id: str = Cookie(None), ilce: str = None):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    query = supabase.table("projects").select("*, users:firma_id(sirket_unvani, ad_soyad, profil_foto)").eq("durum", "Aktif")
    if ilce:
        query = query.ilike("ilce", f"%{ilce.strip()}%")

    projects = query.order("created_at", desc=True).execute().data or []

    return templates.TemplateResponse(
        request=request,
        name="projects/catalog.html",
        context={"projects": projects, "selected_ilce": ilce or ""}
    )

# ================= 2. PROJE DETAY SAYFASI =================
@router.get("/detail/{project_id}", response_class=HTMLResponse)
def get_project_detail(request: Request, project_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    is_company = False
    is_owner = False

    try:
        u_res = supabase.table("users").select("firma_tipi").eq("id", clean_user_id).single().execute()
        if u_res.data:
            user_type = str(u_res.data.get("firma_tipi") or "").lower()
            if user_type in ["sirket", "proje_firmasi", "developer"]:
                is_company = True

        p_res = supabase.table("projects").select(
            "*, users:firma_id(sirket_unvani, ad_soyad, telefon, profil_foto)"
        ).eq("id", project_id).single().execute()
        project = p_res.data
        
        if project and str(project.get("firma_id")) == clean_user_id:
            is_owner = True

    except Exception as e:
        print(f"[PROJE DETAY HATASI]: {e}")
        project = None

    if not project:
        return RedirectResponse(url="/company/projects" if is_company else "/projects", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="projects/detail.html",
        context={
            "project": project,
            "is_company": is_company,
            "is_owner": is_owner
        }
    )

# ================= 3. PROJE DETAY & MÜŞTERİ TESCİL SAYFASI =================
@router.get("/{project_id}/register-client", response_class=HTMLResponse)
def get_register_client_page(request: Request, project_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    try:
        p_res = supabase.table("projects").select("*, users:firma_id(sirket_unvani, ad_soyad, telefon)").eq("id", project_id).single().execute()
        project = p_res.data
    except Exception:
        project = None

    if not project:
        return RedirectResponse(url="/projects", status_code=303)

    available_room_types = []
    desc = str(project.get("aciklama") or "")
    if "[DAIRE_TIPLERI]:" in desc:
        try:
            raw_types = desc.split("[DAIRE_TIPLERI]:")[1].strip().split("\n")[0]
            available_room_types = [t.strip() for t in raw_types.split(",") if t.strip()]
        except Exception:
            available_room_types = []

    if not available_room_types:
        available_room_types = ["1+1 Daire", "2+1 Daire", "3+1 Daire", "4+1 Daire", "Villa"]

    return templates.TemplateResponse(
        request=request,
        name="projects/register_client.html",
        context={
            "project": project,
            "available_room_types": available_room_types
        }
    )

# ================= 4. MÜŞTERİ TESCİLİNİ VERİTABANINA KAYDET =================
@router.post("/{project_id}/register-client")
def post_register_client(
    request: Request,
    project_id: str,
    musteri_ad_soyad: str = Form(...),
    musteri_telefon: str = Form(...),
    ilgilenilen_daire_tipi: str = Form(None),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    masked_phone = mask_phone_number(musteri_telefon)
    tescil_code = generate_tescil_no()

    try:
        supabase.table("project_customer_registrations").insert({
            "tescil_no": tescil_code,
            "project_id": project_id,
            "agent_id": clean_user_id,
            "musteri_ad_soyad": musteri_ad_soyad.strip(),
            "musteri_telefon": musteri_telefon.strip(),
            "musteri_telefon_maskeli": masked_phone,
            "ilgilenilen_daire_tipi": ilgilenilen_daire_tipi.strip() if ilgilenilen_daire_tipi else None,
            "butce_araligi": "Talepte Belirtildi",
            "durum": "Doğrulandı",
            "koruma_suresi_gun": 90,
            "sms_dogrulandi": True
        }).execute()

        p_check = supabase.table("project_partners").select("id").eq("project_id", project_id).eq("agent_id", clean_user_id).execute()
        if not p_check.data:
            supabase.table("project_partners").insert({
                "project_id": project_id,
                "agent_id": clean_user_id,
                "partner_seviyesi": "Standart",
                "durum": "Aktif"
            }).execute()

        # PROJE FİRMASINA BİLDİRİM GÖNDER
        try:
            agent_res = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
            emlakci_adi = agent_res.data.get("ad_soyad") if agent_res.data else "Bir Danışman"

            proj_res = supabase.table("projects").select("ad, firma_id").eq("id", project_id).single().execute()
            if proj_res.data and proj_res.data.get("firma_id"):
                firma_id = proj_res.data.get("firma_id")
                proje_adi = proj_res.data.get("ad") or "Projenize"

                send_notification(
                    user_id=firma_id,
                    baslik="Yeni Müşteri Tescili! 📋",
                    icerik=f"{emlakci_adi} adlı emlakçı '{proje_adi}' projenize müşteri tescili yaptı ({musteri_ad_soyad.strip()}).",
                    hedef_url="/company/registrations"
                )
        except Exception as notif_err:
            print(f"[TESCİL FİRMA BİLDİRİM HATASI]: {notif_err}")

        return RedirectResponse(url=f"/projects/registration-success?code={tescil_code}", status_code=303)
    except Exception as e:
        print(f"[TESCİL HATASI]: {e}")
        return RedirectResponse(url=f"/projects/{project_id}/register-client", status_code=303)

# ================= 5. TESCİL BAŞARI EKRANI =================
@router.get("/registration-success", response_class=HTMLResponse)
def get_registration_success(request: Request, code: str = "", user_id: str = Cookie(None)):
    return templates.TemplateResponse(
        request=request,
        name="projects/registration_success.html",
        context={"tescil_code": code}
    )

# ================= 6. EMLAKÇININ TESCİLLİ MÜŞTERİLERİ =================
@router.get("/my-registrations", response_class=HTMLResponse)
def get_my_registrations(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    registrations = []

    try:
        reg_res = supabase.table("project_customer_registrations").select(
            "*, projects(ad, il, ilce, partner_komisyon_orani, users:firma_id(sirket_unvani, ad_soyad))"
        ).eq("agent_id", clean_user_id).order("created_at", desc=True).execute()

        raw_regs = reg_res.data or []
        now = datetime.now(timezone.utc)

        for r in raw_regs:
            end_date_str = r.get("koruma_bitis_tarihi")
            days_left = 90
            if end_date_str:
                try:
                    clean_dt_str = end_date_str.replace("Z", "+00:00")
                    end_dt = datetime.fromisoformat(clean_dt_str)
                    delta = (end_dt - now).days
                    days_left = max(delta, 0)
                except Exception:
                    days_left = 90
            r["days_left"] = days_left
            registrations.append(r)

    except Exception as e:
        print(f"[MY REGISTRATIONS HATASI]: {e}")
        registrations = []

    return templates.TemplateResponse(
        request=request,
        name="projects/my_registrations.html",
        context={"registrations": registrations}
    )

# ================= 7. TESCİLİ İPTAL ET (FİRMAYA BİLDİRİMLİ) =================
@router.post("/cancel-registration/{registration_id}")
def post_cancel_registration(registration_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    try:
        # İptal etmeden önce firma ve proje bilgisini al
        reg_info = supabase.table("project_customer_registrations").select(
            "musteri_ad_soyad, projects(ad, firma_id)"
        ).eq("id", registration_id).single().execute()

        supabase.table("project_customer_registrations").update({
            "durum": "İptal Edildi"
        }).eq("id", registration_id).eq("agent_id", clean_user_id).execute()

        # Proje firmasına iptal bildirimi gönder
        if reg_info.data and reg_info.data.get("projects"):
            firma_id = reg_info.data["projects"].get("firma_id")
            proje_adi = reg_info.data["projects"].get("ad") or "Proje"
            m_ad = reg_info.data.get("musteri_ad_soyad") or "Müşteri"

            agent_res = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
            emlakci_adi = agent_res.data.get("ad_soyad") if agent_res.data else "Emlakçı"

            if firma_id:
                send_notification(
                    user_id=firma_id,
                    baslik="İşbirliği / Müşteri Tescili İptal Edildi ⚠️",
                    icerik=f"{emlakci_adi} adlı emlakçı ile olan '{proje_adi}' projesindeki işbirliğiniz ({m_ad}) iptal edildi.",
                    hedef_url="/company/registrations"
                )

    except Exception as e:
        print(f"[TESCİL İPTAL HATASI]: {e}")

    return RedirectResponse(url="/collaborations/my?tab=tamamlanan&subtab=projeler", status_code=303)