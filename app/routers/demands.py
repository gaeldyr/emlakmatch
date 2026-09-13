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

# 405 Method Not Allowed hatasını önlemek için GET yönlendirmesi (Sayfa yenilemelerinde)
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

    target_ilce = ilce.strip().lower()
    target_type = gayrimenkul_tipi.strip().lower()
    min_b = int(min_butce) if min_butce else 0
    max_b = int(max_butce) if max_butce else 0

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

        score = 0
        p_ilce = str(p.get("ilce") or "").strip().lower()
        p_type = str(p.get("gayrimenkul_tipi") or "").strip().lower()
        p_price = int(p.get("fiyat") or 0)
        p_oda = str(p.get("oda") or "").strip().lower()

        # İlçe Uyumu (40)
        if p_ilce == target_ilce:
            score += 40

        # Tip Uyumu (25)
        if p_type == target_type or target_type == "diğer":
            score += 25

        # Fiyat Uyumu (20)
        if min_b > 0 and max_b > 0:
            if min_b <= p_price <= max_b:
                score += 20
            elif (min_b * 0.9) <= p_price <= (max_b * 1.1):
                score += 10
        elif max_b > 0:
            if p_price <= max_b:
                score += 20
            elif p_price <= (max_b * 1.1):
                score += 10
        else:
            score += 10

        # Oda Uyumu (15)
        if oda_sayisi and p_oda:
            target_oda = oda_sayisi.strip().lower()
            if target_oda == p_oda:
                score += 15
            elif target_oda.split("+")[0] == p_oda.split("+")[0]:
                score += 8

        if score >= 40:
            p["match_score"] = min(score, 100)
            matched_portfolios.append(p)

    matched_portfolios.sort(key=lambda x: x["match_score"], reverse=True)

    # ================= 3. ŞİRKET PROJELERİNİ TARA (40 NİTELİK & DİNAMİK PUANLAMA) =================
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

    # Danışmanın talep formunda seçtiği nitelik listesi
    demand_features_set = set()
    if ozellikler:
        if isinstance(ozellikler, str):
            demand_features_set = {f.strip().lower() for f in ozellikler.split(",") if f.strip()}
        else:
            demand_features_set = {str(f).strip().lower() for f in ozellikler if f}

    for prj in all_projects:
        prj_score = 0
        prj_ilce = str(prj.get("ilce") or "").strip().lower()
        prj_min_f = int(prj.get("min_fiyat") or 0)
        prj_max_f = int(prj.get("max_fiyat") or 0)
        prj_type = str(prj.get("proje_tipi") or "").strip().lower()
        prj_desc = str(prj.get("aciklama") or "").lower()

        # 1. İlçe Uyumu (35 Puan)
        if prj_ilce == target_ilce:
            prj_score += 35
        elif target_ilce in prj_ilce or prj_ilce in target_ilce:
            prj_score += 20

        # 2. Tip Uyumu (20 Puan)
        if prj_type in target_type or target_type in prj_type or target_type == "diğer":
            prj_score += 20

        # 3. Fiyat Örtüşmesi (15 Puan)
        if max_b > 0:
            if (min_b == 0 or prj_max_f >= min_b) and (prj_min_f <= max_b):
                prj_score += 15
            elif prj_min_f <= (max_b * 1.2):
                prj_score += 8
        else:
            prj_score += 15

        # 4. Donatı & Nitelik Eşleşmesi (30 Puan)
        matched_feature_count = 0
        total_demand_features = len(demand_features_set)

        if total_demand_features > 0:
            for feat in demand_features_set:
                if feat in prj_desc:
                    matched_feature_count += 1
            
            feature_ratio = matched_feature_count / total_demand_features
            prj_score += round(feature_ratio * 30)
        else:
            # Talepte donatı seçilmediyse taban puan
            prj_score += 15

        final_prj_score = min(prj_score, 100)
        prj["match_score"] = final_prj_score
        prj["matched_feature_count"] = matched_feature_count

        if final_prj_score >= 35:
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