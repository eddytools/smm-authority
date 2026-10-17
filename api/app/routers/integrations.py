import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.access import get_accessible_venture
from app.crypto import TokenCipherError
from app.deps import CurrentUser, DbSession, SettingsDep
from app.models import Connection, OAuthAttempt, Role, User, Venture
from app.publishers import ProviderError, pkce_pair
from app.schemas import ORM

log = logging.getLogger("smm.integrations")
router = APIRouter(prefix="/ventures/{venture_id}/integrations", tags=["publishing"])
callback_router = APIRouter(prefix="/integrations", tags=["publishing"])
PLATFORMS = ("linkedin", "x")
ATTEMPT_TTL = timedelta(minutes=10)


class IntegrationOut(BaseModel):
    platform: str
    label: str
    configured: bool  # the server has this platform's app credentials and an encryption key
    connected: bool
    account_name: str | None = None
    status: str | None = None  # "active" | "needs_reconnect"
    auto_publish: bool | None = None
    expires_at: datetime | None = None


class IntegrationUpdate(BaseModel):
    auto_publish: bool


class ConnectOut(BaseModel):
    authorize_url: str


def _publishing(request: Request):
    return request.app.state.publishing


def _platform(request: Request, platform: str):
    if platform not in PLATFORMS:
        raise HTTPException(404, "Unknown platform")
    return _publishing(request).providers[platform]


def _redirect_uri(settings, platform: str) -> str:
    return f"{settings.public_api_url.rstrip('/')}/integrations/{platform}/callback"


def _out(pub, platform: str, conn: Connection | None) -> IntegrationOut:
    p = pub.providers[platform]
    return IntegrationOut(
        platform=platform, label=p.label, configured=pub.configured(platform), connected=conn is not None,
        account_name=conn.account_name if conn else None, status=conn.status if conn else None,
        auto_publish=conn.auto_publish if conn else None, expires_at=conn.expires_at if conn else None,
    )


@router.get("", response_model=list[IntegrationOut])
def list_integrations(venture_id: int, request: Request, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    conns = {c.platform: c for c in db.scalars(select(Connection).where(Connection.venture_id == venture_id))}
    return [_out(_publishing(request), p, conns.get(p)) for p in PLATFORMS]


@router.post("/{platform}/connect", response_model=ConnectOut)
def connect(venture_id: int, platform: str, request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep):
    get_accessible_venture(db, venture_id, user)
    provider = _platform(request, platform)
    if not _publishing(request).configured(platform):
        raise HTTPException(503, f"{provider.label} publishing isn't set up on this server. An administrator needs to add the app credentials and an encryption key.")
    now = datetime.now(timezone.utc)
    db.execute(delete(OAuthAttempt).where(OAuthAttempt.expires_at < now))
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair() if provider.uses_pkce else (None, None)
    db.add(OAuthAttempt(state=state, user_id=user.id, venture_id=venture_id, platform=platform, code_verifier=verifier, expires_at=now + ATTEMPT_TTL))
    db.commit()
    return ConnectOut(authorize_url=provider.authorize_url(_redirect_uri(settings, platform), state, challenge))


@callback_router.get("/{platform}/callback")
def callback(platform: str, request: Request, db: DbSession, settings: SettingsDep, code: str | None = None, state: str | None = None, error: str | None = None):
    """The platform sends the user's browser here. It isn't authenticated with a token, so the one-time `state` we issued
    (bound to the user, venture and platform, and expiring in 10 minutes) is what ties this back to a signed-in user."""
    dash = settings.dashboard_url.rstrip("/")
    provider = _platform(request, platform)
    attempt = db.scalar(select(OAuthAttempt).where(OAuthAttempt.state == (state or ""))) if state else None
    if attempt is None or attempt.platform != platform:
        return RedirectResponse(f"{dash}/?{urlencode({'publishing_error': 'invalid_state'})}", 303)
    venture_id, user_id, verifier, expires = attempt.venture_id, attempt.user_id, attempt.code_verifier, attempt.expires_at
    db.delete(attempt)  # single use, whatever happens next
    db.commit()

    def back(**q):
        return RedirectResponse(f"{dash}/ventures/{venture_id}/publishing?{urlencode(q)}", 303)

    if expires < datetime.now(timezone.utc):
        return back(error="expired")
    if error or not code:
        return back(error="denied")
    user, venture = db.get(User, user_id), db.get(Venture, venture_id)
    if user is None or not user.is_active or venture is None or (venture.owner_id != user.id and user.role != Role.admin):
        return back(error="not_allowed")
    cipher = _publishing(request).cipher
    try:
        tokens = provider.exchange_code(code, _redirect_uri(settings, platform), verifier)
        account = provider.account(tokens.access_token)
    except ProviderError as exc:
        log.warning("connect %s failed: %s", platform, exc.message)  # never log tokens or the code
        return back(error="exchange_failed")
    now = datetime.now(timezone.utc)
    conn = db.scalar(select(Connection).where(Connection.venture_id == venture_id, Connection.platform == platform))
    if conn is None:
        conn = Connection(venture_id=venture_id, platform=platform, account_id=account.external_id, account_name=account.name, access_token_enc="")
        db.add(conn)
    conn.account_id, conn.account_name, conn.status, conn.connected_by_id = account.external_id, account.name, "active", user.id
    conn.access_token_enc = cipher.encrypt(tokens.access_token)
    conn.refresh_token_enc = cipher.encrypt(tokens.refresh_token) if tokens.refresh_token else None
    conn.expires_at = now + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    db.commit()
    return back(connected=platform)


def _get_conn(db, venture_id: int, platform: str) -> Connection:
    conn = db.scalar(select(Connection).where(Connection.venture_id == venture_id, Connection.platform == platform))
    if conn is None:
        raise HTTPException(404, "Not connected")
    return conn


@router.patch("/{platform}", response_model=IntegrationOut)
def update_integration(venture_id: int, platform: str, body: IntegrationUpdate, request: Request, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    _platform(request, platform)
    conn = _get_conn(db, venture_id, platform)
    conn.auto_publish = body.auto_publish
    db.commit()
    return _out(_publishing(request), platform, conn)


@router.delete("/{platform}", status_code=204)
def disconnect(venture_id: int, platform: str, request: Request, user: CurrentUser, db: DbSession):
    """Forgets the stored tokens. The user should also remove the app's access from their LinkedIn/X account settings."""
    get_accessible_venture(db, venture_id, user)
    _platform(request, platform)
    db.delete(_get_conn(db, venture_id, platform))
    db.commit()
