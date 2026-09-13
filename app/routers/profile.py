import uuid
from fastapi import APIRouter, Request, Form, Cookie, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.security import is_in_network, can_request_network, is_relationship_blocked
from app.utils.notifier import send_notification

router = APIRouter(prefix="/profile", tags=["Profile"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ================= 1. KENDİ PROFİLİM =================
@router.get("", response_class=HTMLResponse)
@router.get("/view", response_class=HTMLResponse)
def get_my_profile(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        u_res = supabase.table("users").select("*").eq("id", clean_user_id).single().execute()
        user = u_res.data or {}
    except Exception:
        user = {}

    try:
        inv_res = supabase.table("invitation_codes").select("*").eq("olusturan_id", clean_user_id).order("created_at").execute()
        invites = inv_res.data or []
    except Exception:
        invites = []

    network_partners = []
    network_count = 0
    try:
        net_res = (
            supabase.table("agent_networks")
            .select("agent_id_1, agent_id_2, created_at")
            .eq("durum", "Aktif")
            .or_(f"agent_id_1.eq.{clean_user_id},agent_id_2.eq.{clean_user_id}")
            .execute()
        )
        rows = net_res.data or []
        partner_ids = []
        for r in rows:
            p_id = r["agent_id_2"] if r["agent_id_1"] == clean_user_id else r["agent_id_1"]
            if p_id not in partner_ids:
                partner_ids.append(p_id)

        network_count = len(partner_ids)
        if partner_ids:
            u_p_res = (
                supabase.table("users")
                .select("id, ad_soyad, profil_foto, sirket_unvani, calistigi_ilceler")
                .in_("id", partner_ids)
                .execute()
            )
            partners_dict = {p["id"]: p for p in (u_p_res.data or [])}

            for pid in partner_ids:
                p_item = partners_dict.get(pid)
                if not p_item:
                    continue
                pc = supabase.table("portfolios").select("id", count="exact").eq("porfoy_sahibi_id", pid).eq("durum", "Aktif").execute()
                p_item["port_count"] = pc.count or 0
                network_partners.append(p_item)
    except Exception:
        network_partners, network_count = [], 0

    try:
        port_res = supabase.table("portfolios").select("*").eq("porfoy_sahibi_id", clean_user_id).order("created_at", desc=True).execute()
        portfolios = port_res.data or []
        port_count = len(portfolios)
    except Exception:
        portfolios, port_count = [], 0

    try:
        collab_count_res = (
            supabase.table("collaboration_requests")
            .select("id", count="exact")
            .or_(f"talep_alan_id.eq.{clean_user_id},talep_gonderen_id.eq.{clean_user_id}")
            .eq("durum", "Tamamlandı")
            .execute()
        )
        completed_collabs = collab_count_res.count or 0
    except Exception:
        completed_collabs = 0

    try:
        incoming_net = (
            supabase.table("agent_networks")
            .select("id, agent_id_1, created_at, sender:agent_id_1(id, ad_soyad, sirket_unvani, profil_foto)")
            .eq("agent_id_2", clean_user_id)
            .eq("durum", "Beklemede")
            .execute()
        )
        incoming_requests = incoming_net.data or []
    except Exception:
        incoming_requests = []

    try:
        rec_res = (
            supabase.table("agent_reviews")
            .select("id, puan, yorum, created_at, reviewer_id")
            .eq("target_agent_id", clean_user_id)
            .order("created_at", desc=True)
            .execute()
        )
        received_reviews = rec_res.data or []
        for r in received_reviews:
            pid = r.get("reviewer_id")
            r_user = {"ad_soyad": "Meslektaşınız", "profil_foto": None}
            if pid:
                pu = supabase.table("users").select("ad_soyad, profil_foto, sirket_unvani").eq("id", pid).single().execute()
                if pu.data:
                    r_user = pu.data
            r["author"] = r_user

        avg_score = round(sum([r["puan"] for r in received_reviews]) / len(received_reviews), 1) if received_reviews else 5.0
    except Exception:
        received_reviews, avg_score = [], 5.0

    try:
        blk_res = supabase.table("blocked_users").select("blocked_id").eq("blocker_id", clean_user_id).execute()
        blocked_rows = blk_res.data or []
        blocked_users_list = []
        for b in blocked_rows:
            target_id = str(b.get("blocked_id")).strip()
            if target_id:
                bu = supabase.table("users").select("id, ad_soyad, sirket_unvani").eq("id", target_id).execute()
                if bu.data and len(bu.data) > 0:
                    blocked_users_list.append({"target_user": bu.data[0]})
    except Exception:
        blocked_users_list = []

    return templates.TemplateResponse(
        request=request,
        name="profile/index.html",
        context={
            "is_me": True,
            "user": user,
            "invites": invites,
            "network_count": network_count,
            "network_partners": network_partners,
            "port_count": port_count,
            "portfolios": portfolios,
            "completed_collabs": completed_collabs,
            "received_reviews": received_reviews,
            "avg_score": avg_score,
            "blocked_users_list": blocked_users_list,
            "incoming_requests": incoming_requests
        }
    )

# ================= 2. BAŞKA BROKER'I İNCELEME (VISIBILITY KORUMALI) =================
@router.get("/view/{target_user_id}", response_class=HTMLResponse)
def get_other_profile(request: Request, target_user_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_target_id = str(target_user_id).strip()

    if clean_user_id == clean_target_id:
        return RedirectResponse(url="/profile", status_code=303)

    in_network = is_in_network(clean_user_id, clean_target_id)
    can_request = can_request_network(clean_user_id, clean_target_id)

    net_req_status = None
    try:
        n_res = supabase.table("agent_networks").select("durum, agent_id_1").or_(
            f"and(agent_id_1.eq.{clean_user_id},agent_id_2.eq.{clean_target_id}),"
            f"and(agent_id_1.eq.{clean_target_id},agent_id_2.eq.{clean_user_id})"
        ).execute()
        if n_res.data:
            net_req_status = n_res.data[0].get("durum")
    except Exception:
        pass

    try:
        u_res = supabase.table("users").select("*").eq("id", clean_target_id).single().execute()
        target_user = u_res.data or {}

        rev_res = (
            supabase.table("agent_reviews")
            .select("puan, yorum, created_at, reviewer_id")
            .eq("target_agent_id", clean_target_id)
            .order("created_at", desc=True)
            .execute()
        )
        received_reviews = rev_res.data or []
        for r in received_reviews:
            pid = r.get("reviewer_id")
            r_user = {"ad_soyad": "Meslektaşınız", "profil_foto": None}
            if pid:
                pu = supabase.table("users").select("ad_soyad, profil_foto").eq("id", pid).single().execute()
                if pu.data:
                    r_user = pu.data
            r["author"] = r_user

        avg_score = round(sum([r["puan"] for r in received_reviews]) / len(received_reviews), 1) if received_reviews else 5.0

        net_res = supabase.table("agent_networks").select("id", count="exact").eq("durum", "Aktif").or_(f"agent_id_1.eq.{clean_target_id},agent_id_2.eq.{clean_target_id}").execute()
        network_count = net_res.count or 0

        # GÖRÜNÜRLÜK (VISIBILITY) FİLTRESİ
        # Private olanlar dışarıdan profile giren kimseye ASLA görünmez
        all_target_ports = (
            supabase.table("portfolios")
            .select("*")
            .eq("porfoy_sahibi_id", clean_target_id)
            .eq("durum", "Aktif")
            .neq("visibility", "private") # Private portföyler elenir
            .execute()
        )
        candidate_ports = all_target_ports.data or []

        # İki danışmanın ortak üye olduğu grupları tespit et
        my_gm = supabase.table("group_members").select("group_id").eq("user_id", clean_user_id).execute()
        my_groups = {str(item["group_id"]) for item in (my_gm.data or []) if item.get("group_id")}

        target_gm = supabase.table("group_members").select("group_id").eq("user_id", clean_target_id).execute()
        target_groups = {str(item["group_id"]) for item in (target_gm.data or []) if item.get("group_id")}

        has_common_group = bool(my_groups.intersection(target_groups))

        # Ortak işbirlikleri olan portföy kimlikleri
        shared_collabs = supabase.table("collaboration_requests").select("ilgili_ilan_id").or_(
            f"and(talep_gonderen_id.eq.{clean_user_id},talep_alan_id.eq.{clean_target_id}),"
            f"and(talep_gonderen_id.eq.{clean_target_id},talep_alan_id.eq.{clean_user_id})"
        ).execute()
        shared_ids = {str(c.get("ilgili_ilan_id")).strip() for c in (shared_collabs.data or []) if c.get("ilgili_ilan_id")}

        visible_portfolios = []
        hidden_portfolio_count = 0

        for p in candidate_ports:
            p_id_str = str(p.get("id")).strip()
            p_vis = str(p.get("visibility") or "network").lower()

            can_view = False
            if in_network or (p_id_str in shared_ids):
                # Ağ ortağıysa veya üzerinde aktif işbirliği varsa görür
                can_view = True
            elif p_vis == "network":
                # Ağ genelinde açık portföy
                can_view = True
            elif p_vis == "group" and has_common_group:
                # Sadece gruplarım seçilmiş ve en az 1 ortak grup varsa görür
                can_view = True

            if can_view:
                visible_portfolios.append(p)
            else:
                hidden_portfolio_count += 1

    except Exception as e:
        print(f"[HEDEF PROFİL HATASI]: {e}")
        target_user, received_reviews, visible_portfolios = {}, [], []
        avg_score, hidden_portfolio_count, network_count = 5.0, 0, 0

    return templates.TemplateResponse(
        request=request,
        name="profile/index.html",
        context={
            "is_me": False,
            "user": target_user,
            "received_reviews": received_reviews,
            "avg_score": avg_score,
            "network_count": network_count,
            "network_partners": [],
            "port_count": len(visible_portfolios),
            "in_network": in_network,
            "can_request": can_request,
            "net_req_status": net_req_status,
            "portfolios": visible_portfolios,
            "hidden_portfolio_count": hidden_portfolio_count
        }
    )

# ================= 3. AĞ İSTEĞİ GÖNDERME =================
@router.post("/network/request/{target_id}")
def post_request_network(target_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_target_id = str(target_id).strip()

    if not can_request_network(clean_user_id, clean_target_id):
        return RedirectResponse(url=f"/profile/view/{clean_target_id}?error=no_history", status_code=303)

    try:
        supabase.table("agent_networks").insert({
            "agent_id_1": clean_user_id,
            "agent_id_2": clean_target_id,
            "baglanti_tipi": "isbirligi",
            "durum": "Beklemede"
        }).execute()

        sender = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        s_name = sender.data.get("ad_soyad") if sender.data else "Bir meslektaşınız"

        send_notification(
            user_id=clean_target_id,
            baslik="Yeni Ağ Bağlantısı İsteği",
            icerik=f"{s_name} sizi iş ortağı ağına eklemek istiyor.",
            hedef_url="/profile"
        )
    except Exception as e:
        print(f"[AĞ İSTEĞİ HATASI]: {e}")

    return RedirectResponse(url=f"/profile/view/{clean_target_id}", status_code=303)

# ================= 4. AĞ İSTEĞİ YANITLAMA =================
@router.post("/network/respond/{network_id}")
def post_respond_network(network_id: str, action: str = Form(...), user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    new_status = "Aktif" if action == "accept" else "Reddedildi"
    try:
        n_res = supabase.table("agent_networks").select("agent_id_1").eq("id", network_id).eq("agent_id_2", user_id).single().execute()
        supabase.table("agent_networks").update({"durum": new_status}).eq("id", network_id).execute()

        if action == "accept" and n_res.data:
            send_notification(
                user_id=n_res.data.get("agent_id_1"),
                baslik="Ağ Bağlantınız Onaylandı",
                icerik="Meslektaşınız ağ isteğinizi kabul etti. Artık karşılıklı tüm portföyleri inceleyebilirsiniz.",
                hedef_url=f"/profile/view/{user_id}"
            )
    except Exception as e:
        print(f"[AĞ YANITLAMA HATASI]: {e}")

    return RedirectResponse(url="/profile", status_code=303)

# ================= 5. PROFİL DÜZENLEME =================
@router.get("/edit", response_class=HTMLResponse)
def get_edit_profile(request: Request, first_login: int = 0, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    try:
        u_res = supabase.table("users").select("*").eq("id", clean_user_id).single().execute()
        user = u_res.data or {}
    except Exception:
        user = {}

    return templates.TemplateResponse(
        request=request,
        name="profile/edit.html",
        context={"user": user, "first_login": bool(first_login)}
    )

@router.post("/update")
async def post_update_profile(
    request: Request,
    ad_soyad: str = Form(...),
    telefon: str = Form(None),
    sirket_unvani: str = Form(None),
    calisma_bolgesi: str = Form(None),
    profil_foto: UploadFile = File(None),
    yetki_belgesi: UploadFile = File(None),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    update_data = {
        "ad_soyad": ad_soyad.strip(),
        "telefon": telefon.strip() if telefon else None,
        "sirket_unvani": sirket_unvani.strip() if sirket_unvani else None,
        "calisma_bolgesi": calisma_bolgesi.strip() if calisma_bolgesi else None
    }

    if profil_foto and profil_foto.filename:
        try:
            bytes_data = await profil_foto.read()
            if len(bytes_data) > 0:
                ext = profil_foto.filename.split(".")[-1].lower() if "." in profil_foto.filename else "jpg"
                file_name = f"avatar_{clean_user_id}_{uuid.uuid4().hex[:6]}.{ext}"
                supabase.storage.from_("portfolios").upload(
                    path=file_name,
                    file=bytes_data,
                    file_options={"content-type": profil_foto.content_type or f"image/{ext}"}
                )
                update_data["profil_foto"] = supabase.storage.from_("portfolios").get_public_url(file_name)
        except Exception as e:
            print(f"[AVATAR UPLOAD HATASI]: {e}")

    if yetki_belgesi and yetki_belgesi.filename:
        try:
            bytes_data = await yetki_belgesi.read()
            if len(bytes_data) > 0:
                ext = yetki_belgesi.filename.split(".")[-1].lower() if "." in yetki_belgesi.filename else "jpg"
                file_name = f"belge_{clean_user_id}_{uuid.uuid4().hex[:6]}.{ext}"
                supabase.storage.from_("portfolios").upload(
                    path=file_name,
                    file=bytes_data,
                    file_options={"content-type": yetki_belgesi.content_type or f"image/{ext}"}
                )
                update_data["yetki_belgesi_url"] = supabase.storage.from_("portfolios").get_public_url(file_name)
                update_data["belge_onayli"] = True
        except Exception as e:
            print(f"[BELGE UPLOAD HATASI]: {e}")

    try:
        supabase.table("users").update(update_data).eq("id", clean_user_id).execute()
    except Exception as e:
        print(f"[PROFİL GÜNCELLEME HATASI]: {e}")

    return RedirectResponse(url="/profile", status_code=303)