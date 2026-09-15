from typing import List
from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.security import is_relationship_blocked
from app.routers.portfolios import TURKEY_DISTRICTS

router = APIRouter(prefix="/demands", tags=["Demands"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 1. ALICIM VAR FORMU
@router.get("/add", response_class=HTMLResponse)
def get_add_demand(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request, 
        name="demands/add.html",
        context={"turkey_data": TURKEY_DISTRICTS}
    )

@router.get("/search")
def get_search_redirect():
    return RedirectResponse(url="/demands/add", status_code=303)

# 2. TALEP KAYDET VE EŞLEŞEN PORTFÖYLERİ + PROJELERİ GETİR
@router.post("/search")
def post_search_demand(
    request: Request,
    il: str = Form("İstanbul"),
    ilce: str = Form(...),
    gayrimenkul_tipi: str = Form(...),
    min_butce: int = Form(0),
    max_butce: int = Form(0),
    oda_sayisi: str = Form(None),
    ozellikler: List[str] = Form([]),
    musteri_durumu: str = Form("Hazır Alıcı"),
    visibility: str = Form("network"),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    # 1. Talebi veritabanına kaydet
    demand_id = None
    try:
        ins = supabase.table("buyer_demands").insert({
            "user_id": clean_user_id,
            "il": il.strip() if il else "İstanbul",
            "ilce": ilce.strip(),
            "gayrimenkul_tipi": gayrimenkul_tipi.strip(),
            "min_butce": int(min_butce) if min_butce else None,
            "max_butce": int(max_butce) if max_butce else None,
            "oda_sayisi": oda_sayisi.strip() if oda_sayisi else None,
            "ozellikler": ozellikler,
            "musteri_durumu": musteri_durumu,
            "visibility": visibility,
            "durum": "Aktif"
        }).execute()
        if ins.data:
            demand_id = ins.data[0]["id"]
    except Exception as e:
        print(f"[DEMAND KAYIT HATASI]: {e}")

    # Kullanıcının üye olduğu grupları al
    my_group_ids = set()
    try:
        my_gm = supabase.table("group_members").select("group_id").eq("user_id", clean_user_id).execute()
        my_group_ids = {str(item["group_id"]) for item in (my_gm.data or []) if item.get("group_id")}
    except Exception:
        my_group_ids = set()

    target_il = il.strip().lower() if il else "istanbul"
    target_ilce = ilce.strip().lower()
    min_b = int(min_butce) if min_butce else 0
    max_b = int(max_butce) if max_butce else 0

    # Talepte seçilen oda/ünite tipleri seti
    demand_unit_types = set()
    if oda_sayisi:
        demand_unit_types = {u.strip().lower() for u in oda_sayisi.split(",") if u.strip()}

    # Talepte seçilen donatılar/özellikler seti
    demand_features_set = set()
    if ozellikler:
        if isinstance(ozellikler, str):
            demand_features_set = {f.strip().lower() for f in ozellikler.split(",") if f.strip()}
        else:
            demand_features_set = {str(f).strip().lower() for f in ozellikler if f}
    total_demand_features = len(demand_features_set)

    # ================= 2. EMLAKÇI PORTFÖYLERİNİ TARA =================
    matched_portfolios = []
    try:
        ports_res = (
            supabase.table("portfolios")
            .select("*, users:porfoy_sahibi_id(id, ad_soyad, telefon, profil_foto, sirket_unvani)")
            .neq("porfoy_sahibi_id", clean_user_id)
            .neq("visibility", "private")
            .eq("durum", "Aktif")
            .execute()
        )
        all_portfolios = ports_res.data or []
    except Exception as e:
        all_portfolios = []
        print(f"[PORTFÖY TARAMA HATASI]: {e}")

    for p in all_portfolios:
        owner_id = str(p.get("porfoy_sahibi_id") or "").strip()
        if is_relationship_blocked(clean_user_id, owner_id):
            continue

        p_vis = str(p.get("visibility") or "network").lower()
        if p_vis == "group":
            try:
                owner_gm = supabase.table("group_members").select("group_id").eq("user_id", owner_id).execute()
                owner_groups = {str(item["group_id"]) for item in (owner_gm.data or []) if item.get("group_id")}
                if not my_group_ids.intersection(owner_groups):
                    continue
            except Exception:
                continue

        p_il = str(p.get("il") or "İstanbul").strip().lower()
        p_ilce = str(p.get("ilce") or "").strip().lower()

        # KURAL 1: İl ve İlçe uyuşmuyorsa direkt elenir
        if p_il != target_il or p_ilce != target_ilce:
            continue

        score = 30  # İl ve ilçe tuttuğu için 30 puan cepte

        # KURAL 2: Mahalle veya Site uyuşuyorsa +%10
        p_mahalle = str(p.get("mahalle_site") or "").strip().lower()
        if p_mahalle:
            score += 10

        # KURAL 3: Bütçe aralıkları uyuyorsa +%10
        p_price = int(p.get("fiyat") or 0)
        if min_b > 0 and max_b > 0:
            if min_b <= p_price <= max_b:
                score += 10
        elif max_b > 0:
            if p_price <= max_b:
                score += 10
        elif min_b > 0:
            if p_price >= min_b:
                score += 10
        else:
            score += 10

        # KURAL 4: Odalar uyuşuyorsa +%10
        p_oda = str(p.get("oda") or "").strip().lower()
        if demand_unit_types:
            if any(p_oda == u or p_oda in u or u in p_oda for u in demand_unit_types):
                score += 10
        else:
            score += 10

        # KURAL 5: Kalan 40 özellikten kaç tanesini seçmişse (%40 / toplam seçilen özellik * eşleşen)
        p_desc = str(p.get("kisa_aciklama") or "").lower()
        if total_demand_features > 0:
            matched_features = sum(1 for feat in demand_features_set if feat in p_desc)
            score += round((matched_features / total_demand_features) * 40)
        else:
            score += 40

        # KURAL 6: %60'ı geçemeyen listeye alınmaz
        if score >= 60:
            p["match_score"] = min(score, 100)
            matched_portfolios.append(p)

    matched_portfolios.sort(key=lambda x: x["match_score"], reverse=True)

    # ================= 3. ŞİRKET PROJELERİNİ TARA =================
    matched_projects = []
    try:
        proj_res = (
            supabase.table("projects")
            .select("*, users:firma_id(id, ad_soyad, sirket_unvani, marka_adi, telefon, profil_foto)")
            .eq("durum", "Aktif")
            .execute()
        )
        all_projects = proj_res.data or []
    except Exception as e:
        all_projects = []
        print(f"[PROJE TARAMA HATASI]: {e}")

    for prj in all_projects:
        prj_il = str(prj.get("il") or "İstanbul").strip().lower()
        prj_ilce = str(prj.get("ilce") or "").strip().lower()

        # KURAL 1: İl ve İlçe uyuşmuyorsa direkt elenir
        if prj_il != target_il or prj_ilce != target_ilce:
            continue

        prj_score = 30  # İl ve ilçe tuttuğu için 30 puan cepte

        # KURAL 2: Bölge / Mahalle uyuşuyorsa +%10
        prj_bolge = str(prj.get("bolge") or "").strip().lower()
        if prj_bolge:
            prj_score += 10

        # KURAL 3: Bütçe aralıkları uyuyorsa +%10
        prj_min_f = int(prj.get("min_fiyat") or 0)
        prj_max_f = int(prj.get("max_fiyat") or 0)
        if max_b > 0:
            if (min_b == 0 or prj_max_f >= min_b) and (prj_min_f <= max_b):
                prj_score += 10
        else:
            prj_score += 10

        # KURAL 4: Daire / Ünite tipleri uyuşuyorsa +%10
        prj_desc = str(prj.get("aciklama") or "").lower()
        if demand_unit_types:
            if any(u in prj_desc for u in demand_unit_types):
                prj_score += 10
        else:
            prj_score += 10

        # KURAL 5: Kalan 40 özellikten kaç tanesini seçmişse (%40 / toplam seçilen özellik * eşleşen)
        matched_feature_count = 0
        if total_demand_features > 0:
            matched_feature_count = sum(1 for feat in demand_features_set if feat in prj_desc)
            prj_score += round((matched_feature_count / total_demand_features) * 40)
        else:
            prj_score += 40

        # KURAL 6: %60'ı geçemeyen listeye alınmaz
        if prj_score >= 60:
            final_prj_score = min(prj_score, 100)
            prj["match_score"] = final_prj_score
            prj["matched_feature_count"] = matched_feature_count
            matched_projects.append(prj)

    matched_projects.sort(key=lambda x: x["match_score"], reverse=True)

    criteria = {
        "il": il,
        "ilce": ilce,
        "gayrimenkul_tipi": gayrimenkul_tipi,
        "min_butce": min_b,
        "max_butce": max_b,
        "oda_sayisi": oda_sayisi,
        "demand_id": demand_id
    }

    return templates.TemplateResponse(
        request=request,
        name="demands/results.html",
        context={
            "results": matched_portfolios,
            "project_results": matched_projects,
            "criteria": criteria
        }
    )