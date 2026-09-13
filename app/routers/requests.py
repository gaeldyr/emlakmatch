from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.notifier import send_notification
from app.utils.security import is_relationship_blocked

try:
    from app.routers.portfolios import TURKEY_DISTRICTS
except ImportError:
    TURKEY_DISTRICTS = {"İstanbul": ["Beşiktaş", "Beykoz", "Kadıköy", "Sarıyer"]}

router = APIRouter(prefix="/requests/referral", tags=["Referrals"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def mask_contact(name: str, phone: str):
    name_parts = (name or "").split()
    masked_name = " ".join([p[0] + "***" for p in name_parts]) if name_parts else "***"
    phone_clean = (phone or "").replace(" ", "")
    masked_phone = phone_clean[:4] + " *** ** " + phone_clean[-2:] if len(phone_clean) >= 6 else "***"
    return masked_name, masked_phone

# 1. YÖNLENDİRME FORMU
@router.get("/add", response_class=HTMLResponse)
def get_referral_add(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request, 
        name="requests/referral.html",
        context={"request": request, "turkey_data": TURKEY_DISTRICTS}
    )

# 2. UZMANLARI LİSTELE & SEÇ
@router.post("/find-agents", response_class=HTMLResponse)
def post_find_agents(
    request: Request,
    musteri_ad_soyad: str = Form(...),
    musteri_telefon: str = Form(...),
    musteri_eposta: str = Form(None),
    il: str = Form("İstanbul"),
    ilce: str = Form(...),
    gayrimenkul_tipi: str = Form(...),
    musteri_butcesi: str = Form("0"),
    isbirligi_kosulu: str = Form("%30 (Yönlendiren) - %70 (Kapatan)"),
    ek_not: str = Form(""),
    user_id: str = Cookie(None)
):
    clean_user_id = str(user_id).strip() if user_id else None
    if not clean_user_id or clean_user_id == "None":
        return RedirectResponse(url="/login", status_code=303)

    clean_butce_str = str(musteri_butcesi or "0").replace(".", "").replace(",", "").replace(" ", "").strip()
    int_butce = int(clean_butce_str) if clean_butce_str.isdigit() else 0

    clean_ilce = (ilce or "").strip().lower()
    clean_type = (gayrimenkul_tipi or "").strip().lower()

    matched_agents = []
    try:
        u_res = (
            supabase.table("users")
            .select("id, ad_soyad, sirket_unvani, profil_foto, calistigi_ilceler, uzmanlik_alanlari")
            .neq("id", clean_user_id)
            .eq("durum", "aktif")
            .execute()
        )
        agents = u_res.data or []

        for a in agents:
            target_id = a.get("id")
            try:
                if is_relationship_blocked(clean_user_id, target_id):
                    continue
            except Exception:
                pass

            raw_districts = a.get("calistigi_ilceler") or []
            if isinstance(raw_districts, str):
                districts = [d.strip().lower() for d in raw_districts.split(",") if d.strip()]
            else:
                districts = [str(d).strip().lower() for d in raw_districts if d]

            raw_specs = a.get("uzmanlik_alanlari") or []
            if isinstance(raw_specs, str):
                specs = [s.strip().lower() for s in raw_specs.split(",") if s.strip()]
            else:
                specs = [str(s).strip().lower() for s in raw_specs if s]

            score = 50
            if clean_ilce in districts:
                score += 35
            if clean_type in specs or clean_type == "diğer":
                score += 15

            a["score"] = min(score, 99)
            matched_agents.append(a)

        matched_agents.sort(key=lambda x: x["score"], reverse=True)
    except Exception as e:
        print(f"[UZMAN BULMA HATASI]: {e}")
        matched_agents = []

    client_data = {
        "musteri_ad_soyad": musteri_ad_soyad,
        "musteri_telefon": musteri_telefon,
        "musteri_eposta": musteri_eposta,
        "il": il,
        "ilce": ilce,
        "gayrimenkul_tipi": gayrimenkul_tipi,
        "musteri_butcesi": int_butce,
        "isbirligi_kosulu": isbirligi_kosulu,
        "ek_not": ek_not
    }

    return templates.TemplateResponse(
        request=request,
        name="requests/referral.html",
        context={
            "request": request,
            "agents": matched_agents,
            "client": client_data,
            "turkey_data": TURKEY_DISTRICTS
        }
    )

# 3. YÖNLENDİRMEYİ GÖNDER
@router.post("/send")
def post_send_referral_request(
    target_agent_id: str = Form(...),
    musteri_ad_soyad: str = Form(...),
    musteri_telefon: str = Form(...),
    musteri_eposta: str = Form(None),
    il: str = Form(...),
    ilce: str = Form(...),
    gayrimenkul_tipi: str = Form(...),
    musteri_butcesi: str = Form("0"),
    isbirligi_kosulu: str = Form(...),
    ek_not: str = Form(""),
    user_id: str = Cookie(None)
):
    clean_user_id = str(user_id).strip() if user_id else None
    if not clean_user_id or clean_user_id == "None":
        return RedirectResponse(url="/login", status_code=303)

    clean_butce_str = str(musteri_butcesi or "0").replace(".", "").replace(",", "").replace(" ", "").strip()
    int_butce = int(clean_butce_str) if clean_butce_str.isdigit() else 0

    payload = {
        "gonderen_id": clean_user_id,
        "alici_id": target_agent_id.strip(),
        "musteri_ad_soyad": musteri_ad_soyad.strip(),
        "musteri_telefon": musteri_telefon.strip(),
        "musteri_eposta": musteri_eposta.strip() if musteri_eposta else None,
        "il": il.strip(),
        "ilce": ilce.strip(),
        "gayrimenkul_tipi": gayrimenkul_tipi.strip(),
        "musteri_butcesi": int_butce if int_butce > 0 else None,
        "isbirligi_kosulu": isbirligi_kosulu.strip(),
        "ek_not": ek_not.strip() if ek_not else None,
        "durum": "beklemede"
    }

    try:
        supabase.table("client_referrals").insert(payload).execute()

        sender = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        s_name = sender.data.get("ad_soyad") if sender.data else "Bir meslektaşınız"

        send_notification(
            user_id=target_agent_id.strip(),
            baslik="Yeni Müşteri Yönlendirmesi",
            icerik=f"{s_name} size {ilce} bölgesinde müşteri yönlendirdi ({isbirligi_kosulu}).",
            hedef_url="/requests/referral/list?tab=gelen"
        )
    except Exception as e:
        print(f"[REFERRAL KAYIT HATASI]: {e}")

    return RedirectResponse(url="/requests/referral/list?tab=giden", status_code=303)

# 4. YÖNLENDİRME LİSTESİ (GARANTİLİ VE SAĞLAM EŞLEŞTİRME)
@router.get("/list", response_class=HTMLResponse)
def get_referral_list(request: Request, tab: str = "gelen", user_id: str = Cookie(None)):
    clean_user_id = str(user_id).strip() if user_id else None
    if not clean_user_id or clean_user_id == "None":
        return RedirectResponse(url="/login", status_code=303)

    records = []
    try:
        # Ham veriyi direkt çek (join çökmesini önlemek için)
        if tab == "gelen":
            res = supabase.table("client_referrals").select("*").eq("alici_id", clean_user_id).order("created_at", desc=True).execute()
        else:
            res = supabase.table("client_referrals").select("*").eq("gonderen_id", clean_user_id).order("created_at", desc=True).execute()

        raw_records = res.data or []

        # İlgili kullanıcıları eşleştir
        user_ids = set()
        for r in raw_records:
            if r.get("gonderen_id"):
                user_ids.add(str(r["gonderen_id"]))
            if r.get("alici_id"):
                user_ids.add(str(r["alici_id"]))

        users_map = {}
        if user_ids:
            u_res = supabase.table("users").select("id, ad_soyad, telefon, sirket_unvani").in_("id", list(user_ids)).execute()
            users_map = {str(u["id"]): u for u in (u_res.data or [])}

        for r in raw_records:
            g_id = str(r.get("gonderen_id"))
            a_id = str(r.get("alici_id"))
            r["gonderen"] = users_map.get(g_id, {"ad_soyad": "Meslektaşınız", "telefon": "-", "sirket_unvani": "Broker"})
            r["alici"] = users_map.get(a_id, {"ad_soyad": "Meslektaşınız", "telefon": "-", "sirket_unvani": "Broker"})

            is_accepted = (r.get("durum") not in ["beklemede", "reddedildi"])
            if tab == "gelen" and not is_accepted:
                m_name, m_phone = mask_contact(r.get("musteri_ad_soyad"), r.get("musteri_telefon"))
                r["display_name"] = m_name
                r["display_phone"] = m_phone
                r["is_masked"] = True
            else:
                r["display_name"] = r.get("musteri_ad_soyad")
                r["display_phone"] = r.get("musteri_telefon")
                r["is_masked"] = False

            records.append(r)

    except Exception as e:
        print(f"[REFERRAL LISTE HATASI]: {e}")
        records = []

    return templates.TemplateResponse(
        request=request,
        name="requests/referral_list.html",
        context={"request": request, "tab": tab, "referrals": records}
    )

# 5. KABUL / RET
@router.post("/respond/{referral_id}")
def post_referral_respond(referral_id: str, action: str = Form(...), user_id: str = Cookie(None)):
    clean_user_id = str(user_id).strip() if user_id else None
    if not clean_user_id or clean_user_id == "None":
        return RedirectResponse(url="/login", status_code=303)

    new_status = "kabul_edildi" if action == "accept" else "reddedildi"
    try:
        supabase.table("client_referrals").update({"durum": new_status}).eq("id", referral_id).eq("alici_id", clean_user_id).execute()

        ref = supabase.table("client_referrals").select("gonderen_id").eq("id", referral_id).single().execute()
        if ref.data:
            receiver = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
            alici_adi = receiver.data.get("ad_soyad") if receiver.data else "Meslektaşınız"

            send_notification(
                user_id=ref.data.get("gonderen_id"),
                baslik="Müşteri Yönlendirmeniz Yanıtlandı",
                icerik=f"{alici_adi} müşterinizi {'kabul etti!' if action == 'accept' else 'reddetti.'}",
                hedef_url="/requests/referral/list?tab=giden"
            )
    except Exception as e:
        print(f"[REFERRAL YANIT HATASI]: {e}")

    return RedirectResponse(url="/requests/referral/list?tab=gelen", status_code=303)

@router.post("/update-stage/{referral_id}")
def post_update_stage(referral_id: str, asama: str = Form(...), user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    try:
        supabase.table("client_referrals").update({"durum": asama}).eq("id", referral_id).execute()
    except Exception as e:
        print(f"[AŞAMA GÜNCELLEME HATASI]: {e}")

    return RedirectResponse(url="/requests/referral/list", status_code=303)