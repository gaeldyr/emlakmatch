from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.security import is_relationship_blocked
from app.utils.notifier import send_notification

router = APIRouter(prefix="/network", tags=["Network"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ================= 1. AĞIM ANA SAYFASI =================
@router.get("", response_class=HTMLResponse)
@router.get("/my", response_class=HTMLResponse)
def get_my_network(request: Request, tab: str = "ofisim", user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    user_data = {}
    office_data = None
    office_members = []
    my_groups = []
    available_groups = []
    network_partners = []
    invitable_partners = []
    pending_office_invites = []

    try:
        # 1. Kullanıcı Bilgisini Çek
        u_res = supabase.table("users").select("*").eq("id", clean_user_id).single().execute()
        user_data = u_res.data or {}

        # Eğer kullanıcıda office_id varsa ofis verisini tablodan ayrıca güvenli şekilde çek
        office_id = user_data.get("office_id")
        if office_id:
            try:
                off_res = supabase.table("offices").select("*").eq("id", office_id).single().execute()
                office_data = off_res.data or {}
            except Exception as o_err:
                print(f"[OFİS GETİRME HATA]: {o_err}")
                office_data = None

        # 2. Emlakçının Doğrudan Ağ Ortakları (Davet Kodu Bağlantıları)
        net_res = (
            supabase.table("agent_networks")
            .select("agent_id_1, agent_id_2")
            .eq("durum", "Aktif")
            .or_(f"agent_id_1.eq.{clean_user_id},agent_id_2.eq.{clean_user_id}")
            .execute()
        )
        partner_ids = set()
        for r in (net_res.data or []):
            p_id = r["agent_id_2"] if str(r["agent_id_1"]).strip() == clean_user_id else r["agent_id_1"]
            partner_ids.add(str(p_id).strip())

        if partner_ids:
            agents_q = supabase.table("users").select(
                "id, ad_soyad, telefon, eposta, profil_foto, sirket_unvani, calistigi_ilceler, uzmanlik_alanlari, office_id"
            ).in_("id", list(partner_ids)).execute()
            for a in (agents_q.data or []):
                aid = str(a.get("id")).strip()
                if not is_relationship_blocked(clean_user_id, aid):
                    pc = supabase.table("portfolios").select("id", count="exact").eq("porfoy_sahibi_id", aid).eq("durum", "Aktif").execute()
                    a["port_count"] = pc.count or 0
                    a["is_direct_partner"] = True
                    network_partners.append(a)
                    if not a.get("office_id"):
                        invitable_partners.append(a)

        # 3. OFİS ÜYELERİ LİSTESİ
        if office_id:
            m_res = (
                supabase.table("users")
                .select("id, ad_soyad, telefon, eposta, profil_foto, office_role, sirket_unvani")
                .eq("office_id", office_id)
                .execute()
            )
            office_members = m_res.data or []
        else:
            try:
                inv_res = supabase.table("office_invitations").select(
                    "id, office_id, sender_id, created_at, offices:office_id(ad, sehir, ilce), sender:sender_id(ad_soyad)"
                ).eq("receiver_id", clean_user_id).eq("durum", "beklemede").execute()
                pending_office_invites = inv_res.data or []
            except Exception:
                pending_office_invites = []

        # 4. GRUPLARIM VERİLERİ
        gm_res = supabase.table("group_members").select("group_id, rol, groups(*)").eq("user_id", clean_user_id).execute()
        joined_group_ids = set()
        seen_joined_names = set()

        for item in (gm_res.data or []):
            g = item.get("groups")
            if g and g.get("ad") not in seen_joined_names and g.get("durum") == "aktif":
                seen_joined_names.add(g.get("ad"))
                g["my_role"] = item.get("rol")
                mc = supabase.table("group_members").select("id", count="exact").eq("group_id", g.get("id")).execute()
                g["members_count"] = mc.count or 1
                my_groups.append(g)
                joined_group_ids.add(g.get("id"))

        all_g_res = supabase.table("groups").select("*").eq("durum", "aktif").order("created_at", desc=True).execute()
        seen_available_names = set()

        for g in (all_g_res.data or []):
            g_name = g.get("ad")
            if g.get("id") not in joined_group_ids and g_name not in seen_available_names and g_name not in seen_joined_names:
                seen_available_names.add(g_name)
                mc = supabase.table("group_members").select("id", count="exact").eq("group_id", g.get("id")).execute()
                g["members_count"] = mc.count or 0
                available_groups.append(g)

    except Exception as e:
        print(f"[AĞIM VERİ DERLEME HATASI]: {e}")

    return templates.TemplateResponse(
        request=request,
        name="network/index.html",
        context={
            "tab": tab,
            "user": user_data,
            "office": office_data,
            "office_members": office_members,
            "invitable_partners": invitable_partners,
            "pending_office_invites": pending_office_invites,
            "my_groups": my_groups,
            "available_groups": available_groups,
            "partners": network_partners,
            "msg": request.query_params.get("msg")
        }
    )
# ================= 2. YENİ OFİS KURMA =================
@router.post("/offices/create")
def post_create_office(
    ad: str = Form(...),
    sehir: str = Form("İstanbul"),
    ilce: str = Form(...),
    adres: str = Form(None),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        # Zaten bir ofisi var mı kontrolü (Sadece 1 ofis kuralı)
        u_chk = supabase.table("users").select("office_id").eq("id", clean_user_id).single().execute()
        if u_chk.data and u_chk.data.get("office_id"):
            return RedirectResponse(url="/network?tab=ofisim&msg=already_has_office", status_code=303)

        # 1. Ofisi oluştur
        office_payload = {
            "ad": ad.strip(),
            "kurucu_id": clean_user_id,
            "sehir": sehir.strip() if sehir else "İstanbul",
            "ilce": ilce.strip(),
            "adres": adres.strip() if adres else None
        }
        o_res = supabase.table("offices").insert(office_payload).execute()
        if not o_res.data:
            return RedirectResponse(url="/network?tab=ofisim&msg=office_create_failed", status_code=303)

        new_office_id = o_res.data[0]["id"]

        # 2. Kurucuyu ofisin sahibi (founder) olarak ata
        supabase.table("users").update({
            "office_id": new_office_id,
            "office_role": "founder"
        }).eq("id", clean_user_id).execute()

        return RedirectResponse(url="/network?tab=ofisim&msg=office_created", status_code=303)

    except Exception as e:
        print(f"[OFİS KURMA HATASI]: {e}")
        return RedirectResponse(url="/network?tab=ofisim&msg=error", status_code=303)

# ================= 3. AĞDAKİ MESLEKTAŞI OFİSE DAVET ET =================
@router.post("/offices/invite")
def post_invite_to_office(
    target_agent_id: str = Form(...),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_target_id = str(target_agent_id).strip()

    try:
        # Davet edenin ofis bilgisi
        u_res = supabase.table("users").select("ad_soyad, office_id, offices:office_id(ad)").eq("id", clean_user_id).single().execute()
        u_data = u_res.data or {}
        office_id = u_data.get("office_id")
        office_name = u_data.get("offices", {}).get("ad") if u_data.get("offices") else "Ofis"
        inviter_name = u_data.get("ad_soyad") or "Meslektaşınız"

        if not office_id:
            return RedirectResponse(url="/network?tab=ofisim&msg=no_office", status_code=303)

        # Hedef kişinin zaten ofisi var mı?
        target_res = supabase.table("users").select("office_id").eq("id", clean_target_id).single().execute()
        if target_res.data and target_res.data.get("office_id"):
            return RedirectResponse(url="/network?tab=ofisim&msg=target_already_has_office", status_code=303)

        # Zaten bekleyen davet var mı?
        chk_inv = supabase.table("office_invitations").select("id").eq("office_id", office_id).eq("receiver_id", clean_target_id).eq("durum", "beklemede").execute()
        if not chk_inv.data or len(chk_inv.data) == 0:
            supabase.table("office_invitations").insert({
                "office_id": office_id,
                "sender_id": clean_user_id,
                "receiver_id": clean_target_id,
                "durum": "beklemede"
            }).execute()

            # Davet edilen emlakçıya bildirim gönder
            send_notification(
                user_id=clean_target_id,
                baslik="Ofis Daveti Aldınız 🏢",
                icerik=f"{inviter_name} sizi '{office_name}' ofisine katılmaya davet etti.",
                hedef_url="/network?tab=ofisim"
            )

        return RedirectResponse(url="/network?tab=ofisim&msg=invite_sent", status_code=303)

    except Exception as e:
        print(f"[OFİS DAVET HATASI]: {e}")
        return RedirectResponse(url="/network?tab=ofisim&msg=error", status_code=303)

# ================= 4. OFİS DAVETİNİ YANITLA (KABUL / RED) =================
@router.post("/offices/respond-invite/{invite_id}")
def post_respond_office_invite(
    invite_id: str,
    action: str = Form(...),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        inv_res = supabase.table("office_invitations").select("*, offices:office_id(ad, kurucu_id)").eq("id", invite_id).eq("receiver_id", clean_user_id).single().execute()
        inv = inv_res.data
        if not inv:
            return RedirectResponse(url="/network?tab=ofisim", status_code=303)

        office_id = inv.get("office_id")
        office_name = inv.get("offices", {}).get("ad") if inv.get("offices") else "Ofis"
        u_info = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        my_name = u_info.data.get("ad_soyad") if u_info.data else "Meslektaşınız"

        if action == "accept":
            # 1 ofis kontrolü
            u_chk = supabase.table("users").select("office_id").eq("id", clean_user_id).single().execute()
            if u_chk.data and u_chk.data.get("office_id"):
                return RedirectResponse(url="/network?tab=ofisim&msg=already_has_office", status_code=303)

            # Kullanıcıyı üye yap
            supabase.table("users").update({
                "office_id": office_id,
                "office_role": "member"
            }).eq("id", clean_user_id).execute()

            supabase.table("office_invitations").update({"durum": "kabul_edildi"}).eq("id", invite_id).execute()

            # Davet gönderene ve ofis kurucusuna teyit bildirimi
            send_notification(
                user_id=inv.get("sender_id"),
                baslik="Ofis Davetiniz Kabul Edildi! 🏢",
                icerik=f"{my_name} ofis davetinizi kabul etti ve ofise katıldı.",
                hedef_url="/network?tab=ofisim"
            )
        else:
            supabase.table("office_invitations").update({"durum": "reddedildi"}).eq("id", invite_id).execute()

    except Exception as e:
        print(f"[OFİS DAVET YANITLAMA HATASI]: {e}")

    return RedirectResponse(url="/network?tab=ofisim", status_code=303)

# ================= 5. OFİSTEN ÜYE ÇIKARMA (SADECE KURUCU) =================
@router.post("/offices/remove-member/{member_id}")
def post_remove_office_member(
    member_id: str,
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_member_id = str(member_id).strip()

    try:
        # İsteyen kişi kurucu mu?
        u_res = supabase.table("users").select("office_id, office_role, offices:office_id(ad)").eq("id", clean_user_id).single().execute()
        u_data = u_res.data or {}

        if u_data.get("office_role") != "founder":
            return RedirectResponse(url="/network?tab=ofisim&msg=unauthorized", status_code=303)

        office_id = u_data.get("office_id")
        office_name = u_data.get("offices", {}).get("ad") if u_data.get("offices") else "Ofis"

        # Üyeyi ofisten çıkar (Kurucu kendini atamaz)
        if clean_member_id != clean_user_id:
            supabase.table("users").update({
                "office_id": None,
                "office_role": None
            }).eq("id", clean_member_id).eq("office_id", office_id).execute()

            send_notification(
                user_id=clean_member_id,
                baslik="Ofis Üyeliğiniz Sonlandırıldı",
                icerik=f"'{office_name}' kurucusu tarafından ofis üyeliğiniz sonlandırıldı.",
                hedef_url="/network?tab=ofisim"
            )

        return RedirectResponse(url="/network?tab=ofisim&msg=member_removed", status_code=303)

    except Exception as e:
        print(f"[OFİS ÜYE ÇIKARMA HATASI]: {e}")
        return RedirectResponse(url="/network?tab=ofisim&msg=error", status_code=303)

# ================= 6. OFİSİ KAPAT / SİL (SADECE KURUCU) =================
@router.post("/offices/close")
def post_close_office(user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        u_res = supabase.table("users").select("office_id, office_role, offices:office_id(ad)").eq("id", clean_user_id).single().execute()
        u_data = u_res.data or {}

        if u_data.get("office_role") != "founder" or not u_data.get("office_id"):
            return RedirectResponse(url="/network?tab=ofisim&msg=unauthorized", status_code=303)

        office_id = u_data.get("office_id")
        office_name = u_data.get("offices", {}).get("ad") if u_data.get("offices") else "Ofis"

        # Ofisteki tüm üyelerin bağlantısını kopar
        members = supabase.table("users").select("id").eq("office_id", office_id).execute().data or []
        for m in members:
            m_id = str(m["id"])
            if m_id != clean_user_id:
                send_notification(
                    user_id=m_id,
                    baslik="Ofis Kapatıldı",
                    icerik=f"'{office_name}' kurucusu tarafından kapatıldı.",
                    hedef_url="/network?tab=ofisim"
                )

        supabase.table("users").update({"office_id": None, "office_role": None}).eq("office_id", office_id).execute()
        
        # Ofis davetlerini ve ofis kaydını sil
        try:
            supabase.table("office_invitations").delete().eq("office_id", office_id).execute()
        except Exception:
            pass
            
        supabase.table("offices").delete().eq("id", office_id).execute()

        return RedirectResponse(url="/network?tab=ofisim&msg=office_closed", status_code=303)

    except Exception as e:
        print(f"[OFİS KAPATMA HATASI]: {e}")
        return RedirectResponse(url="/network?tab=ofisim&msg=error", status_code=303)

# ================= 7. OFİSTEN KENDİ İSTEĞİYLE AYRILMA (ÜYE) =================
@router.post("/offices/leave")
def post_leave_office(user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        u_res = supabase.table("users").select("ad_soyad, office_id, office_role, offices:office_id(kurucu_id, ad)").eq("id", clean_user_id).single().execute()
        u_data = u_res.data or {}

        # Kurucu ofisi kapatmalıdır, direkt ayrılamaz
        if u_data.get("office_role") == "founder":
            return RedirectResponse(url="/network?tab=ofisim&msg=founder_must_close", status_code=303)

        office_id = u_data.get("office_id")
        founder_id = u_data.get("offices", {}).get("kurucu_id") if u_data.get("offices") else None
        user_name = u_data.get("ad_soyad") or "Bir üye"

        supabase.table("users").update({"office_id": None, "office_role": None}).eq("id", clean_user_id).execute()

        if founder_id:
            send_notification(
                user_id=founder_id,
                baslik="Ofisten Bir Üye Ayrıldı",
                icerik=f"{user_name} ofisinizden kendi isteğiyle ayrıldı.",
                hedef_url="/network?tab=ofisim"
            )

        return RedirectResponse(url="/network?tab=ofisim&msg=left_office", status_code=303)

    except Exception as e:
        print(f"[OFİSTEN AYRILMA HATASI]: {e}")
        return RedirectResponse(url="/network?tab=ofisim&msg=error", status_code=303)

# ================= 8. GRUP İŞLEMLERİ (MEVCUT YAPI KORUNDU) =================
@router.post("/groups/create")
def post_create_group_request(
    ad: str = Form(...),
    kategori: str = Form("Bolge"),
    ilce: str = Form(None),
    aciklama: str = Form(...),
    katilim_tipi: str = Form("acik"),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_name = ad.strip()

    try:
        chk = supabase.table("groups").select("id").ilike("ad", clean_name).execute()
        if chk.data and len(chk.data) > 0:
            return RedirectResponse(url="/network?tab=gruplar&msg=group_exists", status_code=303)

        group_payload = {
            "ad": clean_name,
            "kategori": kategori,
            "ilce": ilce.strip() if ilce else None,
            "aciklama": aciklama.strip(),
            "katilim_tipi": katilim_tipi,
            "kurucu_id": clean_user_id,
            "durum": "onay_bekliyor"
        }
        supabase.table("groups").insert(group_payload).execute()

        admins = supabase.table("users").select("id").eq("rol", "admin").execute()
        for adm in (admins.data or []):
            send_notification(
                user_id=adm["id"],
                baslik="Yeni Grup Kurma Başvurusu 👥",
                icerik=f"'{clean_name}' adlı yeni bir grup kurma talebi onayınızı bekliyor.",
                hedef_url="/admin/dashboard?tab=grup_onaylari"
            )

        return RedirectResponse(url="/network?tab=gruplar&msg=group_pending", status_code=303)
    except Exception as e:
        print(f"[GRUP KURMA TALEBİ HATASI]: {e}")
        return RedirectResponse(url="/network?tab=gruplar&msg=error", status_code=303)

@router.post("/groups/join/{group_id}")
def post_join_group(group_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_group_id = str(group_id).strip()

    try:
        supabase.table("group_members").insert({
            "group_id": clean_group_id,
            "user_id": clean_user_id,
            "rol": "uye"
        }).execute()
    except Exception as e:
        print(f"[GRUBA KATILMA HATASI]: {e}")

    return RedirectResponse(url=f"/network/groups/{clean_group_id}", status_code=303)

@router.post("/groups/leave/{group_id}")
def post_leave_group(group_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_group_id = str(group_id).strip()

    try:
        supabase.table("group_members").delete().eq("group_id", clean_group_id).eq("user_id", clean_user_id).execute()
    except Exception as e:
        print(f"[GRUPTAN AYRILMA HATASI]: {e}")

    return RedirectResponse(url="/network?tab=gruplar", status_code=303)

@router.get("/groups/{group_id}", response_class=HTMLResponse)
def get_group_detail(request: Request, group_id: str, filter_type: str = "all", user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_group_id = str(group_id).strip()

    group_data = {}
    posts = []
    is_member = False
    members_count = 0
    my_active_portfolios = []
    my_active_demands = []

    try:
        g_res = supabase.table("groups").select("*").eq("id", clean_group_id).single().execute()
        group_data = g_res.data or {}

        if not group_data or group_data.get("durum") != "aktif":
            return RedirectResponse(url="/network?tab=gruplar", status_code=303)

        m_chk = supabase.table("group_members").select("id, rol").eq("group_id", clean_group_id).eq("user_id", clean_user_id).execute()
        is_member = bool(m_chk.data and len(m_chk.data) > 0)

        all_m = supabase.table("group_members").select("id", count="exact").eq("group_id", clean_group_id).execute()
        members_count = all_m.count or 0

        my_p_res = supabase.table("portfolios").select("id, gayrimenkul_tipi, ilce, fiyat").eq("porfoy_sahibi_id", clean_user_id).eq("durum", "Aktif").execute()
        my_active_portfolios = my_p_res.data or []

        my_d_res = supabase.table("buyer_demands").select("id, gayrimenkul_tipi, ilce, max_butce").eq("user_id", clean_user_id).eq("durum", "Aktif").execute()
        my_active_demands = my_d_res.data or []

        p_query = (
            supabase.table("group_posts")
            .select("*, author:author_id(id, ad_soyad, sirket_unvani, profil_foto), portfolio:portfolio_id(*), buyer_demand:buyer_demand_id(*)")
            .eq("group_id", clean_group_id)
            .order("created_at", desc=True)
        )
        if filter_type != "all":
            p_query = p_query.eq("post_type", filter_type)

        posts_res = p_query.execute()
        posts = posts_res.data or []

    except Exception as e:
        print(f"[GRUP AKIŞ HATASI]: {e}")

    return templates.TemplateResponse(
        request=request,
        name="network/group_detail.html",
        context={
            "group": group_data,
            "is_member": is_member,
            "members_count": members_count,
            "posts": posts,
            "filter_type": filter_type,
            "my_portfolios": my_active_portfolios,
            "my_demands": my_active_demands,
            "user_id": clean_user_id
        }
    )

@router.post("/groups/{group_id}/post")
def post_create_group_post(
    group_id: str,
    post_type: str = Form(...),
    baslik: str = Form(...),
    icerik: str = Form(""),
    portfolio_id: str = Form(None),
    buyer_demand_id: str = Form(None),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_group_id = str(group_id).strip()

    try:
        payload = {
            "group_id": clean_group_id,
            "author_id": clean_user_id,
            "post_type": post_type,
            "baslik": baslik.strip(),
            "icerik": icerik.strip() if icerik else None,
            "portfolio_id": portfolio_id if portfolio_id and portfolio_id != "none" else None,
            "buyer_demand_id": buyer_demand_id if buyer_demand_id and buyer_demand_id != "none" else None
        }
        supabase.table("group_posts").insert(payload).execute()
    except Exception as e:
        print(f"[GRUP PAYLAŞIM HATASI]: {e}")

    return RedirectResponse(url=f"/network/groups/{clean_group_id}", status_code=303)