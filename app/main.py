from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    warnings, infos = settings.startup_messages()
    for message in warnings:
        logger.warning(message)
    for message in infos:
        logger.info(message)
    yield


app = FastAPI(title="Moving Leads AI", lifespan=lifespan)

from .routes import leads, customers, admin as admin_routes, webhooks
app.include_router(leads.router)
app.include_router(customers.router)
app.include_router(admin_routes.router)
app.include_router(webhooks.router)

# Brand favicon, served inline so every page stops 404ing /favicon.ico (the lone
# console error seen across all three pages). Matches the "ML" topbar mark.
_FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#2f6df6"/>'
    '<text x="16" y="21" font-family="Inter,Segoe UI,sans-serif" font-size="13" '
    'font-weight="700" fill="#fff" text-anchor="middle">ML</text></svg>'
).encode()


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(
        content=_FAVICON,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/health", include_in_schema=False)
async def health():
    # Cheap liveness probe for the platform's health check — intentionally does
    # NOT touch Supabase/OpenAI so pings stay free and can't be a failure source.
    return {"status": "ok"}


# Serve static files
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def _html(filename: str) -> FileResponse:
    # The HTML documents themselves can't be cache-busted via a query string
    # (users type bare URLs), so a stale cached page can silently ship old
    # behavior — e.g. a form that predates the consent field. `no-cache` forces
    # the browser to revalidate; ETag/Last-Modified still yield a 304 when the
    # file is unchanged, so this costs a conditional request, not a full reload.
    return FileResponse(
        FRONTEND_DIR / filename,
        headers={"Cache-Control": "no-cache"},
    )


# Serve the HTML form at the root
@app.get("/", response_class=FileResponse)
async def read_index():
    return _html("index.html")

# Serve admin dashboard
@app.get("/admin", response_class=FileResponse)
async def read_admin():
    return _html("admin.html")


@app.get("/portal", response_class=FileResponse)
async def read_customer_portal():
    return _html("customer.html")
