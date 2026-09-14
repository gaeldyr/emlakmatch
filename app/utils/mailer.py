import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "") # Gmail Uygulama Şifresi

def send_verification_email(target_email: str, code: str) -> bool:
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"[E-POSTA UYARISI]: SMTP bilgileri tanımlı değil! Kod konsola basılıyor: {code}")
        return True  # Bilgiler henüz girilmediyse testi tıkamaz

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"{code} - EMLAKMATCH E-Posta Doğrulama Kodunuz"
        msg["From"] = f"EMLAKMATCH <{SMTP_EMAIL}>"
        msg["To"] = target_email

        html_content = f"""
        <div style="background-color: #0A0F11; padding: 40px 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #ffffff; text-align: center;">
            <div style="max-width: 480px; margin: 0 auto; background-color: #121A1D; border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 35px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                <div style="display: inline-block; width: 50px; height: 50px; background: linear-gradient(135deg, #10b981, #047857); border-radius: 14px; line-height: 50px; font-size: 22px; font-weight: 900; margin-bottom: 20px;">
                    EM
                </div>
                <h2 style="color: #ffffff; margin: 0 0 10px 0; font-size: 22px; font-weight: 800;">E-Posta Adresinizi Doğrulayın</h2>
                <p style="color: #94a3b8; font-size: 13px; margin: 0 0 25px 0; line-height: 1.5;">
                    EMLAKMATCH B2B Gayrimenkul Ağı başvurusunu tamamlamak için aşağıdaki 6 haneli güvenlik kodunu kayıt ekranına giriniz:
                </p>
                <div style="display: inline-block; background-color: rgba(16, 185, 129, 0.1); border: 2px dashed #10b981; border-radius: 14px; padding: 12px 30px; letter-spacing: 6px; font-size: 28px; font-weight: 900; color: #34d399; margin-bottom: 25px;">
                    {code}
                </div>
                <p style="color: #64748b; font-size: 11px; margin: 0;">
                    Bu işlemi siz başlatmadıysanız bu e-postayı dikkate almayınız. Güvenliğiniz için bu kodu kimseyle paylaşmayınız.
                </p>
            </div>
        </div>
        """
        msg.attach(MIMEText(html_content, "html"))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, target_email, msg.as_string())
        server.quit()
        print(f"[E-POSTA BAŞARILI]: {target_email} adresine doğrulama kodu iletildi.")
        return True
    except Exception as e:
        print(f"[E-POSTA GÖNDERME HATASI]: {e}")
        return False