from app.database import supabase

def is_relationship_blocked(user_a: str, user_b: str) -> bool:
    """Kullanıcı A, Kullanıcı B'yi veya Kullanıcı B, Kullanıcı A'yı engellediyse True döner."""
    if not user_a or not user_b or user_a == user_b:
        return False
    try:
        res = (
            supabase.table("blocked_users")
            .select("id")
            .or_(
                f"and(blocker_id.eq.{user_a},blocked_id.eq.{user_b}),"
                f"and(blocker_id.eq.{user_b},blocked_id.eq.{user_a})"
            )
            .execute()
        )
        return bool(res.data and len(res.data) > 0)
    except Exception as e:
        print(f"[ENGEL KONTROL HATASI]: {e}")
        return False

def get_blocked_user_ids(user_id: str) -> list:
    """Kullanıcının engellediği ve kullanıcıyı engelleyen tüm ID'lerin listesini döner."""
    if not user_id:
        return []
    try:
        res = (
            supabase.table("blocked_users")
            .select("blocker_id, blocked_id")
            .or_(f"blocker_id.eq.{user_id},blocked_id.eq.{user_id}")
            .execute()
        )
        blocked_ids = set()
        for row in (res.data or []):
            if row.get("blocker_id") == user_id:
                blocked_ids.add(row.get("blocked_id"))
            else:
                blocked_ids.add(row.get("blocker_id"))
        return list(blocked_ids)
    except Exception:
        return []

def is_in_network(user_a: str, user_b: str) -> bool:
    """İki kullanıcı arasında onaylanmış ('Aktif') bir ağ bağı var mı kontrol eder."""
    if not user_a or not user_b or user_a == user_b:
        return False
    try:
        res = (
            supabase.table("agent_networks")
            .select("id")
            .eq("durum", "Aktif")
            .or_(
                f"and(agent_id_1.eq.{user_a},agent_id_2.eq.{user_b}),"
                f"and(agent_id_1.eq.{user_b},agent_id_2.eq.{user_a})"
            )
            .execute()
        )
        return bool(res.data and len(res.data) > 0)
    except Exception as e:
        print(f"[AĞ KONTROL HATASI]: {e}")
        return False

def can_request_network(user_a: str, user_b: str) -> bool:
    """
    Kullanıcı A'nın Kullanıcı B'ye ağ isteği atabilmesi için:
    1. Aralarında başarılı/başarısız en az bir işbirliği talebi geçmişi olmalı, VEYA
    2. Davet eden / davet edilen ilişkisi bulunmalı.
    """
    if not user_a or not user_b or user_a == user_b:
        return False
    try:
        # 1. İşbirliği geçmişi kontrolü (Herhangi bir statü: Aktif, Tamamlandı, Başarısız, vb.)
        c_res = (
            supabase.table("collaboration_requests")
            .select("id")
            .or_(
                f"and(talep_gonderen_id.eq.{user_a},talep_alan_id.eq.{user_b}),"
                f"and(talep_gonderen_id.eq.{user_b},talep_alan_id.eq.{user_a})"
            )
            .execute()
        )
        if c_res.data and len(c_res.data) > 0:
            return True

        # 2. Davet bağı kontrolü
        i_res = (
            supabase.table("invitation_codes")
            .select("id")
            .or_(
                f"and(olusturan_id.eq.{user_a},kullanan_id.eq.{user_b}),"
                f"and(olusturan_id.eq.{user_b},kullanan_id.eq.{user_a})"
            )
            .execute()
        )
        if i_res.data and len(i_res.data) > 0:
            return True

        return False
    except Exception as e:
        print(f"[AĞ İSTEK YETKİ KONTROLÜ HATASI]: {e}")
        return False