"""
FastAPI application entry point.

Startup sequence:
  1. Init SQLite DB (create tables if needed)
    2. Optionally start legacy browser automation
    3. Serve API + static dashboard + webhooks
"""

import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import init_db
from app.routers.api import router as api_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ------------------------------------------------------------------ startup
    logger.info("Initialising database...")
    await init_db()

    if settings.integration_mode == "legacy":
        from app.instagram_service import instagram_service

        logger.info("Logging in to Instagram via Playwright...")
        try:
            await instagram_service.start()
            logger.info("Instagram login successful.")
        except Exception as exc:
            logger.error("Instagram login failed: %s", exc)
            logger.warning(
                "App is running but legacy browser automation is DISABLED until login succeeds."
            )

        scheduler.add_job(
            run_poll_cycle,
            "interval",
            seconds=settings.poll_interval_seconds,
            id="poll_comments",
            replace_existing=True,
        )
        scheduler.start()
        logger.info(
            "Scheduler started. Polling every %d seconds.", settings.poll_interval_seconds
        )
    else:
        logger.info("Official Instagram API mode enabled; webhook processing only.")

    yield

    # ----------------------------------------------------------------- shutdown
    if settings.integration_mode == "legacy":
        from app.instagram_service import instagram_service

        scheduler.shutdown(wait=False)
        await instagram_service.stop()
        logger.info("Scheduler stopped.")


app = FastAPI(
    title="Instagram Auto-DM",
    description="Keyword-triggered Instagram DM automation",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files & templates
_base_dir = os.path.dirname(__file__)
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(_base_dir, "static")),
    name="static",
)
templates = Jinja2Templates(directory=os.path.join(_base_dir, "templates"))

# API routes
app.include_router(api_router, prefix="/api")


# Dashboard route — serve the SPA shell
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
