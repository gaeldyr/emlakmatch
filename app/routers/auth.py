import uuid
import secrets
import string
import random
from fastapi import APIRouter, Request, Form, Response, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.mailer import send_verification_email

router = APIRouter(tags=["Auth"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def generate_invite_code():
    chars = string.ascii_uppercase + string.digits
    rand_str = ''.join(secrets.choice(chars) for _ in range(6))
    return f"EM-{rand_str}"

# ================= 1. GİRİŞ YAP (EMLAKÇI / ŞİRKET AYRIMI) =================
@router.get("/login", response_class=HTMLResponse)
def get_login(request: Request, type: str = "agent"):
    return templates.TemplateResponse(
        request=request, 
        name="auth/login.html", 
        context={"login_type": type}
    )

@router.post("/login")
def post_login(
    request: Request,
    response: Response,
    eposta: str = Form(...),
    sifre: str = Form(...),
    login_type: str = Form("agent")
):
    clean_email = eposta.strip().lower()
    try:
        res = supabase.table("users").select("*").eq("eposta", clean_email).execute()
        if not res.data:
            return templates.TemplateResponse(
                request=request, 
                name="auth/login.html", 
                context={"error": "Bu e-posta adresiyle kayıtlı kullanıcı bulunamadı.", "login_type": login_type}
            )

        user = res.data[0]
        if user.get("sifre") != sifre:
            return templates.TemplateResponse(
                request=request, 
                name="auth/login.html", 
                context={"error": "Hatalı şifre girdiniz.", "login_type": login_type}
            )

        # Onay Statüsü Kontrolü
        user_status = str(user.get("durum") or "bekliyor").strip().lower()
        if user_status in ["onay_bekliyor", "bekliyor"]:
            return RedirectResponse(url="/auth/pending-approval", status_code=303)
        elif user_status == "reddedildi":
            return templates.TemplateResponse(
                request=request, 
                name="auth/login.html", 
                context={"error": "Üyelik başvurunuz onaylanmamıştır. Bilgi için destekle iletişime geçin.", "login_type": login_type}
            )
        elif user_status == "askida":
            return templates.TemplateResponse(
                request=request, 
                name="auth/login.html", 
                context={"error": "Hesabınız geçici olarak askıya alınmıştır.", "login_type": login_type}
            )

        user_firma_tipi = str(user.get("firma_tipi") or "emlakci").strip().lower()

        # Giriş Türü ve Firma Tipi Denetimi
        if login_type == "company":
            if user_firma_tipi not in ["sirket", "proje_firmasi", "developer"]:
                return templates.TemplateResponse(
                    request=request, 
                    name="auth/login.html", 
                    context={"error": "Bu hesap bir Proje Firması / Şirket hesabı değildir. Emlakçı Girişini kullanınız.", "login_type": "company"}
                )
            redirect_url = "/company/dashboard"
        else:
            if user_firma_tipi in ["sirket", "proje_firmasi", "developer"]:
                return templates.TemplateResponse(
                    request=request, 
                    name="auth/login.html", 
                    context={"error": "Bu hesap bir Şirket hesabıdır. Lütfen Şirket Girişini kullanınız.", "login_type": "agent"}
                )
            redirect_url = "/dashboard"

        redirect = RedirectResponse(url=redirect_url, status_code=303)
        redirect.set_cookie(key="user_id", value=str(user["id"]), max_age=86400 * 30, httponly=True)
        return redirect

    except Exception as e:
        return templates.TemplateResponse(
            request=request, 
            name="auth/login.html", 
            context={"error": f"Giriş hatası: {str(e)}", "login_type": login_type}
        )

# ================= 2. ONAY BEKLEME EKRANI =================
@router.get("/auth/pending-approval", response_class=HTMLResponse)
def get_pending_approval(request: Request):
    return templates.TemplateResponse(request=request, name="auth/pending_approval.html")

# ================= 3. ÇOK ADIMLI KAYIT OL (E-POSTA KODU GÖNDEREN AŞAMA) =================
@router.get("/register", response_class=HTMLResponse)
def get_register(request: Request, type: str = "agent"):
    return templates.TemplateResponse(
        request=request, 
        name="auth/register.html",
        context={"register_type": type}
    )

@router.post("/register")
async def post_register(
    request: Request,
    ad: str = Form(...),
    soyad: str = Form(None),
    telefon: str = Form(...),
    eposta: str = Form(...),
    sifre: str = Form(...),
    sifre_tekrar: str = Form(...),
    davet_kodu: str = Form(None),
    sirket_unvani: str = Form(None),
    marka_adi: str = Form(None),
    yetki_belgesi_no: str = Form(None),
    calistigi_ilceler: str = Form(""),
    uzmanlik_alanlari: str = Form(""),
    firma_tipi: str = Form("emlakci"),
    profil_foto: UploadFile = File(None),
    yetki_belgesi: UploadFile = File(None)
):
    clean_email = eposta.strip().lower()
    clean_code = (davet_kodu or "").strip().upper()
    ad_soyad = f"{ad.strip()} {soyad.strip() if soyad else ''}".strip()
    is_company = (firma_tipi == "sirket")

    if sifre != sifre_tekrar:
        return templates.TemplateResponse(
            request=request, 
            name="auth/register.html", 
            context={
                "error": "Girdiğiniz şifreler birbiriyle eşleşmiyor.",
                "register_type": "company" if is_company else "agent"
            }
        )

    try:
        # 1. E-posta kontrolü
        u_check = supabase.table("users").select("id").eq("eposta", clean_email).execute()
        if u_check.data:
            return templates.TemplateResponse(
                request=request, 
                name="auth/register.html", 
                context={
                    "error": "Bu e-posta adresi zaten sisteme kayıtlı.",
                    "register_type": "company" if is_company else "agent"
                }
            )

        # 2. Davet Kodu Kontrolü (Sadece emlakçılar için zorunlu)
        inviter_id = None
        invite_record_id = None

        if not is_company:
            if not clean_code:
                return templates.TemplateResponse(
                    request=request, 
                    name="auth/register.html", 
                    context={
                        "error": "Davet kodu zorunludur. EmlakMatch sadece davetiye ile üye kabul eder.",
                        "register_type": "agent"
                    }
                )
            if clean_code in ["EMLAK2026", "VIPMATCH"]:
                pass
            else:
                inv_res = supabase.table("invitation_codes").select("*").eq("kod", clean_code).execute()
                if not inv_res.data:
                    return templates.TemplateResponse(
                        request=request, 
                        name="auth/register.html", 
                        context={
                            "error": "Geçersiz davet kodu. EmlakMatch sadece davetiye ile üye kabul eder.",
                            "register_type": "agent"
                        }
                    )
                
                inv_data = inv_res.data[0]
                if inv_data.get("kullanildi"):
                    return templates.TemplateResponse(
                        request=request, 
                        name="auth/register.html", 
                        context={
                            "error": "Bu davet kodu daha önce kullanılmış.",
                            "register_type": "agent"
                        }
                    )
                
                inviter_id = inv_data.get("olusturan_id")
                invite_record_id = inv_data.get("id")

        # 3. Dosyaları Yükle (Avatar / Logo ve Belge)
        avatar_url = None
        if profil_foto and profil_foto.filename:
            try:
                b_avatar = await profil_foto.read()
                if len(b_avatar) > 0:
                    ext = profil_foto.filename.split(".")[-1].lower() if "." in profil_foto.filename else "jpg"
                    f_name = f"avatar_{uuid.uuid4().hex[:8]}.{ext}"
                    supabase.storage.from_("portfolios").upload(
                        path=f_name, 
                        file=b_avatar, 
                        file_options={"content-type": profil_foto.content_type or f"image/{ext}"}
                    )
                    avatar_url = supabase.storage.from_("portfolios").get_public_url(f_name)
            except Exception as e_av:
                print(f"[AVATAR YÜKLEME HATASI]: {e_av}")

        belge_url = None
        if yetki_belgesi and yetki_belgesi.filename:
            try:
                b_belge = await yetki_belgesi.read()
                if len(b_belge) > 0:
                    ext = yetki_belgesi.filename.split(".")[-1].lower() if "." in yetki_belgesi.filename else "jpg"
                    f_name = f"belge_{uuid.uuid4().hex[:8]}.{ext}"
                    supabase.storage.from_("portfolios").upload(
                        path=f_name, 
                        file=b_belge, 
                        file_options={"content-type": yetki_belgesi.content_type or f"image/{ext}"}
                    )
                    belge_url = supabase.storage.from_("portfolios").get_public_url(f_name)
            except Exception as e_bg:
                print(f"[BELGE YÜKLEME HATASI]: {e_bg}")

        # 4. Etiketler ve Kayıt Paketi
        districts_list = [d.strip() for d in calistigi_ilceler.split(",") if d.strip()]
        specialties_list = [s.strip() for s in uzmanlik_alanlari.split(",") if s.strip()]

        user_role = "developer" if is_company else "agent"
        assigned_firma_tipi = "sirket" if is_company else "emlakci"

        pending_payload = {
            "ad_soyad": ad_soyad,
            "eposta": clean_email,
            "telefon": telefon.strip(),
            "sifre": sifre,
            "sirket_unvani": sirket_unvani.strip() if sirket_unvani else None,
            "marka_adi": marka_adi.strip() if marka_adi else None,
            "calistigi_ilceler": districts_list,
            "uzmanlik_alanlari": specialties_list,
            "yetki_belgesi_no": yetki_belgesi_no.strip() if yetki_belgesi_no else None,
            "yetki_belgesi_url": belge_url,
            "profil_foto": avatar_url,
            "durum": "onay_bekliyor",
            "rol": user_role,
            "firma_tipi": assigned_firma_tipi,
            "invite_record_id": invite_record_id,
            "inviter_id": inviter_id
        }

        # 5. 6 Haneli Doğrulama Kodu Üret ve Gönder
        verification_code = str(random.randint(100000, 999999))
        
        # Eski bekleyen kod varsa temizle
        supabase.table("email_verifications").delete().eq("eposta", clean_email).execute()

        # Doğrulama tablosuna geçici paketi kaydet
        supabase.table("email_verifications").insert({
            "eposta": clean_email,
            "kod": verification_code,
            "kayit_verisi": pending_payload
        }).execute()

        # E-posta servisini tetikle
        send_verification_email(clean_email, verification_code)

        # Doğrulama ekranını aç
        return templates.TemplateResponse(
            request=request,
            name="auth/verify_email.html",
            context={"email": clean_email}
        )

    except Exception as e:
        return templates.TemplateResponse(
            request=request, 
            name="auth/register.html", 
            context={
                "error": f"Kayıt işlemi başarısız: {str(e)}",
                "register_type": "company" if is_company else "agent"
            }
        )

# ================= 4. E-POSTA DOĞRULAMA KODU ONAYLAMA =================
@router.post("/auth/verify-email")
def post_verify_email(
    request: Request,
    email: str = Form(...),
    code: str = Form(...)
):
    clean_email = email.strip().lower()
    clean_code = code.strip()

    try:
        chk = supabase.table("email_verifications").select("*").eq("eposta", clean_email).execute()
        if not chk.data:
            return templates.TemplateResponse(
                request=request, 
                name="auth/verify_email.html", 
                context={"email": clean_email, "error": "Doğrulama oturumu bulunamadı, lütfen yeniden kayıt olun."}
            )

        record = chk.data[0]
        if record.get("kod") != clean_code:
            return templates.TemplateResponse(
                request=request, 
                name="auth/verify_email.html", 
                context={"email": clean_email, "error": "Hatalı doğrulama kodu girdiniz."}
            )

        payload = record.get("kayit_verisi") or {}
        invite_record_id = payload.pop("invite_record_id", None)
        inviter_id = payload.pop("inviter_id", None)

        # Kullanıcıyı kalıcı olarak users tablosuna kaydet
        user_res = supabase.table("users").insert(payload).execute()
        new_user = user_res.data[0]
        new_user_id = new_user["id"]

        # Emlakçı ise davet kodunu tüket ve 5 yeni davet kodu tanımla
        if payload.get("firma_tipi") == "emlakci":
            if invite_record_id:
                supabase.table("invitation_codes").update({
                    "kullanildi": True,
                    "kullanan_id": new_user_id
                }).eq("id", invite_record_id).execute()

            if inviter_id:
                try:
                    supabase.table("agent_networks").insert([
                        {"agent_id_1": inviter_id, "agent_id_2": new_user_id, "baglanti_tipi": "davet_kodu", "durum": "Aktif"},
                        {"agent_id_1": new_user_id, "agent_id_2": inviter_id, "baglanti_tipi": "davet_kodu", "durum": "Aktif"}
                    ]).execute()
                except Exception as net_err:
                    print(f"Network bağlama hatası: {net_err}")

            new_codes = [{"olusturan_id": new_user_id, "kod": generate_invite_code()} for _ in range(5)]
            supabase.table("invitation_codes").insert(new_codes).execute()

        # Doğrulama tablosundan geçici kaydı kaldır
        supabase.table("email_verifications").delete().eq("eposta", clean_email).execute()

        return RedirectResponse(url="/auth/pending-approval", status_code=303)

    except Exception as e:
        return templates.TemplateResponse(
            request=request, 
            name="auth/verify_email.html", 
            context={"email": clean_email, "error": f"Onaylama hatası: {str(e)}"}
        )

# ================= ÇIKIŞ YAP =================
@router.get("/logout")
def logout():
    res = RedirectResponse(url="/login", status_code=303)
    res.delete_cookie(key="user_id")
    return res