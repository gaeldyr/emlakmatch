from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import RedirectResponse
from app.database import supabase

router = APIRouter(prefix="/users", tags=["Users"])

@router.post("/block")
def post_block_user(request: Request, target_user_id: str = Form(...), user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_target_id = str(target_user_id).strip()

    if clean_user_id != clean_target_id:
        try:
            chk = (
                supabase.table("blocked_users")
                .select("id")
                .eq("blocker_id", clean_user_id)
                .eq("blocked_id", clean_target_id)
                .execute()
            )
            if not chk.data or len(chk.data) == 0:
                supabase.table("blocked_users").insert({
                    "blocker_id": clean_user_id,
                    "blocked_id": clean_target_id
                }).execute()
        except Exception as e:
            print(f"[ENGELLEME HATASI]: {e}")

    referer = request.headers.get("referer") or "/dashboard"
    return RedirectResponse(url=referer, status_code=303)

@router.post("/unblock")
def post_unblock_user(request: Request, target_user_id: str = Form(...), user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_target_id = str(target_user_id).strip()

    try:
        # KESİN YETKİ KONTROLÜ: Sadece engeli koyan kişi (blocker_id == clean_user_id) kaldırabilir!
        supabase.table("blocked_users").delete()\
            .eq("blocker_id", clean_user_id)\
            .eq("blocked_id", clean_target_id)\
            .execute()
    except Exception as e:
        print(f"[ENGEL KALDIRMA HATASI]: {e}")

    referer = request.headers.get("referer") or "/profile"
    return RedirectResponse(url=referer, status_code=303)