import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

# .env dosyasının tam yolunu garantiye al (proje kök dizini)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

URL = os.getenv("SUPABASE_URL")
KEY = os.getenv("SUPABASE_KEY")

# Değerlerin gelip gelmediğini kontrol et
if not URL or not KEY:
    raise ValueError(f".env dosyasından SUPABASE_URL veya SUPABASE_KEY okunamadı! Okunan URL: {URL}")

supabase: Client = create_client(URL, KEY)