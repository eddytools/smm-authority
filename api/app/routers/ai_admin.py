from fastapi import APIRouter, HTTPException, Request

from app.ai import AIError
from app.deps import AdminUser, SettingsDep

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
def status(request: Request, _: AdminUser, settings: SettingsDep):
    """Which AI vendor and model the server will use. Never returns keys."""
    ai = request.app.state.ai
    vendor = getattr(ai, "name", None) or settings.ai_vendor
    custom_url = vendor == "openai" and settings.openai_base_url.rstrip("/") != "https://api.openai.com/v1"
    return {
        "configured": ai is not None,
        "provider": vendor if ai is not None else None,
        "model": getattr(ai, "model", None),
        "base_url": settings.openai_base_url if custom_url else None,
        "daily_limit_per_user": settings.ai_daily_limit_per_user,
    }


@router.post("/test")
def test(request: Request, _: AdminUser):
    """One tiny real call to the configured model, to prove the key, model name and network path work."""
    ai = request.app.state.ai
    if ai is None or not hasattr(ai, "ping"):
        raise HTTPException(503, "No AI vendor is configured on this server.")
    try:
        tokens_in, tokens_out = ai.ping()
    except AIError as exc:
        raise HTTPException(exc.status_code, exc.message)
    return {"ok": True, "model": ai.model, "input_tokens": tokens_in, "output_tokens": tokens_out}
