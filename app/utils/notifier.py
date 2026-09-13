import uuid
from app.database import supabase

def send_notification(user_id: str, baslik: str, icerik: str, hedef_url: str = None):
    """
    Kullanıcıya bildirim kaydeder.
    UUID hatalarını ve Supabase şema farklılıklarını otomatik tolere eder.
    """
    if not user_id:
        print("\n[BİLDİRİM HATASI]: user_id parametresi boş geldi!\n")
        return False

    raw_uid = str(user_id).strip()
    
    # UUID geçerlilik kontrolü ve temizleme
    try:
        clean_user_id = str(uuid.UUID(raw_uid))
    except Exception:
        # Eğer düzgün bir UUID değilse direkt string halini kullan
        clean_user_id = raw_uid

    target_url = str(hedef_url).strip() if hedef_url else "/dashboard"

    # Olası Supabase tablo varyasyonları
    attempts = [
        # 1. Standart şema: okundu_mu
        {
            "user_id": clean_user_id,
            "baslik": str(baslik).strip(),
            "icerik": str(icerik).strip(),
            "hedef_url": target_url,
            "okundu_mu": False
        },
        # 2. Standart şema: okundu
        {
            "user_id": clean_user_id,
            "baslik": str(baslik).strip(),
            "icerik": str(icerik).strip(),
            "hedef_url": target_url,
            "okundu": False
        },
        # 3. Yalın (sadece zorunlu alanlar)
        {
            "user_id": clean_user_id,
            "baslik": str(baslik).strip(),
            "icerik": str(icerik).strip()
        }
    ]

    for idx, payload in enumerate(attempts, 1):
        try:
            res = supabase.table("notifications").insert(payload).execute()
            if res.data:
                print(f"\n>>> [BİLDİRİM GÖNDERİLDİ - Deneme {idx} Başarılı!]")
                print(f"    Kime: {clean_user_id}")
                print(f"    Başlık: {baslik}")
                print(f"    İçerik: {icerik}\n")
                return True
        except Exception as e:
            print(f"[BİLDİRİM DENEME {idx} BAŞARISIZ]: {e}")

    print("\n[BİLDİRİM KRİTİK]: Hiçbir şema ile notifications tablosuna yazılamadı! Lütfen Supabase tablo sütunlarını kontrol edin.\n")
    return False