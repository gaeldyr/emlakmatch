from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.security import is_relationship_blocked
from app.utils.notifier import send_notification

router = APIRouter(prefix="/messages", tags=["Messages"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def deliver_chat_notification(sender_id: str, receiver_id: str, message_text: str):
    """
    Mesaj bildirimi gönderir ve terminale teşhis bilgisi basar.
    """
    try:
        s_res = supabase.table("users").select("ad_soyad, sirket_unvani, firma_tipi").eq("id", str(sender_id).strip()).single().execute()
        s_user = s_res.data or {}
        
        is_comp = str(s_user.get("firma_tipi") or "").lower() in ["sirket", "proje_firmasi", "developer"]
        if is_comp:
            sender_title = s_user.get("sirket_unvani") or s_user.get("ad_soyad") or "Proje Firması"
            title = f"{sender_title} adlı firmadan yeni mesajınız var 💬"
        else:
            sender_title = s_user.get("ad_soyad") or "Bir Danışman"
            title = f"{sender_title} adlı emlakçıdan yeni mesajınız var 💬"

        body = (message_text[:45] + "...") if len(message_text) > 45 else message_text
        
        # Alıcıya giden bildirim
        send_notification(
            user_id=str(receiver_id).strip(),
            baslik=title,
            icerik=body,
            hedef_url=f"/messages/{sender_id}"
        )
    except Exception as err:
        print(f"[CHAT BİLDİRİM HATASI]: {err}")


# ================= 1. TÜM KONUŞMALAR LİSTESİ =================
@router.get("", response_class=HTMLResponse)
def get_conversations_list(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    conv_list = []

    try:
        res = (
            supabase.table("messages")
            .select("*")
            .or_(f"gonderen_id.eq.{clean_user_id},alici_id.eq.{clean_user_id}")
            .order("created_at", desc=True)
            .execute()
        )
        all_msgs = res.data or []

        conversations = {}
        for m in all_msgs:
            other_id = m.get("alici_id") if m.get("gonderen_id") == clean_user_id else m.get("gonderen_id")
            if other_id and other_id not in conversations:
                try:
                    u_res = supabase.table("users").select("id, ad_soyad, profil_foto, sirket_unvani").eq("id", other_id).execute()
                    other_user = u_res.data[0] if (u_res.data and len(u_res.data) > 0) else {
                        "id": other_id,
                        "ad_soyad": "Kullanıcı",
                        "profil_foto": None
                    }
                except Exception:
                    other_user = {"id": other_id, "ad_soyad": "Kullanıcı", "profil_foto": None}
                
                is_unread = (not bool(m.get("okundu")) and str(m.get("alici_id")) == clean_user_id)
                conversations[other_id] = {
                    "other_user": other_user,
                    "last_message": m.get("mesaj_metni") or "",
                    "last_time": m.get("created_at"),
                    "is_unread": is_unread
                }

        conv_list = list(conversations.values())
    except Exception as e:
        print(f"[MESAJ LİSTESİ HATASI]: {e}")
        conv_list = []

    return templates.TemplateResponse(
        request=request,
        name="messages/list.html",
        context={"conversations": conv_list}
    )


# ================= 2. SOHBET PENCERESİ =================
@router.get("/{other_user_id}", response_class=HTMLResponse)
def get_chat_room(request: Request, other_user_id: str, collab_id: str = None, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_other_id = str(other_user_id).strip()
    is_blocked = is_relationship_blocked(clean_user_id, clean_other_id)

    try:
        u_res = supabase.table("users").select("id, ad_soyad, profil_foto, sirket_unvani, telefon").eq("id", clean_other_id).execute()
        other_user = u_res.data[0] if (u_res.data and len(u_res.data) > 0) else {"id": clean_other_id, "ad_soyad": "Kullanıcı"}
    except Exception:
        other_user = {"id": clean_other_id, "ad_soyad": "Kullanıcı"}

    try:
        m_res = (
            supabase.table("messages")
            .select("*")
            .or_(
                f"and(gonderen_id.eq.{clean_user_id},alici_id.eq.{clean_other_id}),"
                f"and(gonderen_id.eq.{clean_other_id},alici_id.eq.{clean_user_id})"
            )
            .order("created_at", desc=False)
            .execute()
        )
        messages_history = m_res.data or []

        # Sadece sohbet sayfası açıldığında karşıdan gelen mesajları okundu yap
        supabase.table("messages").update({"okundu": True}).eq("gonderen_id", clean_other_id).eq("alici_id", clean_user_id).execute()
    except Exception as e:
        print(f"[SOHBET HATASI]: {e}")
        messages_history = []

    return templates.TemplateResponse(
        request=request,
        name="messages/chat.html",
        context={
            "other_user": other_user,
            "messages": messages_history,
            "current_user_id": clean_user_id,
            "collab_id": collab_id,
            "is_blocked": is_blocked
        }
    )


# ================= 3. MESAJ GÖNDERME (FORM POSTU) =================
@router.post("/send")
def post_send_message(
    receiver_id: str = Form(...),
    message: str = Form(...),
    collab_id: str = Form(None),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_receiver_id = str(receiver_id).strip()

    if is_relationship_blocked(clean_user_id, clean_receiver_id):
        return RedirectResponse(url=f"/messages/{clean_receiver_id}?error=blocked", status_code=303)

    msg_text = message.strip()
    if msg_text:
        try:
            payload = {
                "gonderen_id": clean_user_id,
                "alici_id": clean_receiver_id,
                "mesaj_metni": msg_text,
                "okundu": False
            }
            if collab_id and str(collab_id).strip() and str(collab_id).strip() != "None":
                payload["isbirligi_id"] = str(collab_id).strip()

            supabase.table("messages").insert(payload).execute()
            
            # Bildirim gönder
            deliver_chat_notification(clean_user_id, clean_receiver_id, msg_text)
        except Exception as e:
            print(f"[MESAJ KAYIT HATASI]: {e}")

    redirect_url = f"/messages/{clean_receiver_id}"
    if collab_id and str(collab_id).strip() and str(collab_id).strip() != "None":
        redirect_url += f"?collab_id={collab_id}"
    return RedirectResponse(url=redirect_url, status_code=303)


# ================= 4. CANLI MESAJ YOKLAMA (POLLING) =================
@router.get("/api/poll/{other_user_id}")
def api_poll_messages(other_user_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return JSONResponse({"messages": []}, status_code=401)

    clean_user_id = str(user_id).strip()
    clean_other_id = str(other_user_id).strip()

    if is_relationship_blocked(clean_user_id, clean_other_id):
        return JSONResponse({"messages": []})

    try:
        res = (
            supabase.table("messages")
            .select("id, gonderen_id, alici_id, mesaj_metni, created_at, okundu")
            .or_(
                f"and(gonderen_id.eq.{clean_user_id},alici_id.eq.{clean_other_id}),"
                f"and(gonderen_id.eq.{clean_other_id},alici_id.eq.{clean_user_id})"
            )
            .order("created_at", desc=False)
            .execute()
        )
        all_msgs = res.data or []
        
        # Karşıdan gelenleri okundu yap
        supabase.table("messages").update({"okundu": True}).eq("gonderen_id", clean_other_id).eq("alici_id", clean_user_id).execute()
        return JSONResponse({"messages": all_msgs, "current_user_id": clean_user_id})
    except Exception as e:
        return JSONResponse({"messages": [], "error": str(e)}, status_code=500)


# ================= 5. AJAX MESAJ GÖNDERME API (CHAT.HTML'İN KULLANDIĞI KISIM) =================
@router.post("/api/send")
def api_send_message(
    receiver_id: str = Form(...),
    message: str = Form(...),
    collab_id: str = Form(None),
    user_id: str = Cookie(None)
):
    if not user_id:
        return JSONResponse({"success": False, "error": "Giriş yapılmamış"}, status_code=401)

    clean_user_id = str(user_id).strip()
    clean_receiver_id = str(receiver_id).strip()

    if is_relationship_blocked(clean_user_id, clean_receiver_id):
        return JSONResponse({"success": False, "error": "Bu kullanıcıyla iletişim engellenmiştir."}, status_code=403)

    msg_text = message.strip()
    if not msg_text:
        return JSONResponse({"success": False, "error": "Boş mesaj gönderilemez"})

    try:
        payload = {
            "gonderen_id": clean_user_id,
            "alici_id": clean_receiver_id,
            "mesaj_metni": msg_text,
            "okundu": False
        }
        if collab_id and str(collab_id).strip() and str(collab_id).strip() != "None":
            payload["isbirligi_id"] = str(collab_id).strip()

        insert_res = supabase.table("messages").insert(payload).execute()
        new_msg = insert_res.data[0] if (insert_res.data and len(insert_res.data) > 0) else {}

        # BİLDİRİMİ TETİKLE
        deliver_chat_notification(clean_user_id, clean_receiver_id, msg_text)

        return JSONResponse({"success": True, "message": new_msg})
    except Exception as e:
        print(f"[AJAX MESAJ HATASI]: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)