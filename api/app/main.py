from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from app.ai import AIProvider, AnthropicProvider
from app.config import Settings, get_settings
from app.db import init_schema, make_engine
from app.jobs.ingest import Fetcher, build_fetcher
from app.crypto import TokenCipher, TokenCipherError
from app.publishers import X, LinkedIn
from app.publishing import Publishing
from app.routers import auth, brief, feed, insights, integrations, plan, replies, users, ventures
from app.seed import ensure_admin


def build_publishing(settings: Settings, providers: dict | None = None) -> Publishing:
    try:
        cipher = TokenCipher(settings.token_encryption_key) if settings.token_encryption_key else None
    except TokenCipherError as exc:
        raise RuntimeError(str(exc))
    providers = providers or {
        "linkedin": LinkedIn(settings.linkedin_client_id, settings.linkedin_client_secret, settings.linkedin_api_version),
        "x": X(settings.x_client_id, settings.x_client_secret),
    }
    return Publishing(providers, cipher, settings)


def create_app(settings: Settings | None = None, ai: AIProvider | None = None, fetcher: Fetcher | None = None, providers: dict | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.assert_safe()

    engine = make_engine(settings.database_url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # create_all is fine for the first slice; move to Alembic migrations before the schema stabilises.
        init_schema(engine)
        with session_factory() as db:
            ensure_admin(db, settings)
        yield
        engine.dispose()

    app = FastAPI(title="SMM Authority API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    if ai is None and settings.anthropic_api_key:
        ai = AnthropicProvider(settings.anthropic_api_key, settings.ai_model)
    app.state.ai = ai
    app.state.fetcher = fetcher or build_fetcher(settings)
    app.state.publishing = build_publishing(settings, providers)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(ventures.router)
    app.include_router(brief.router)
    app.include_router(feed.router)
    app.include_router(plan.router)
    app.include_router(plan.framework_router)
    app.include_router(insights.router)
    app.include_router(integrations.router)
    app.include_router(replies.router)
    app.include_router(integrations.callback_router)

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app
