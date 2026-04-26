"""
API routers for automations, leads, DM logs, status, and Instagram webhooks.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, Automation, DMLog, Lead
from app.schemas import (
    AutomationCreate,
    AutomationOut,
    AutomationUpdate,
    DMLogOut,
    LeadOut,
    StatusOut,
)
from app.instagram_api_service import instagram_api_service
from app.instagram_service import instagram_service

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Automations
# ---------------------------------------------------------------------------


@router.get("/automations", response_model=list[AutomationOut])
async def list_automations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Automation).order_by(Automation.created_at.desc()))
    return result.scalars().all()


@router.post("/automations", response_model=AutomationOut, status_code=201)
async def create_automation(
    payload: AutomationCreate, db: AsyncSession = Depends(get_db)
):
    auto = Automation(**payload.model_dump())
    db.add(auto)
    await db.commit()
    await db.refresh(auto)
    return auto


@router.get("/automations/{automation_id}", response_model=AutomationOut)
async def get_automation(automation_id: int, db: AsyncSession = Depends(get_db)):
    auto = await db.get(Automation, automation_id)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    return auto


@router.patch("/automations/{automation_id}", response_model=AutomationOut)
async def update_automation(
    automation_id: int, payload: AutomationUpdate, db: AsyncSession = Depends(get_db)
):
    auto = await db.get(Automation, automation_id)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(auto, field, value)
    await db.commit()
    await db.refresh(auto)
    return auto


@router.delete("/automations/{automation_id}", status_code=204)
async def delete_automation(automation_id: int, db: AsyncSession = Depends(get_db)):
    auto = await db.get(Automation, automation_id)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    await db.delete(auto)
    await db.commit()


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


@router.get("/leads", response_model=list[LeadOut])
async def list_leads(
    automation_id: Optional[int] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    q = select(Lead).order_by(Lead.dm_sent_at.desc()).limit(limit).offset(offset)
    if automation_id is not None:
        q = q.where(Lead.automation_id == automation_id)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/leads/count")
async def leads_count(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count()).select_from(Lead))
    return {"count": result.scalar()}


# ---------------------------------------------------------------------------
# DM Logs
# ---------------------------------------------------------------------------


@router.get("/logs", response_model=list[DMLogOut])
async def list_logs(
    automation_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    q = select(DMLog).order_by(DMLog.created_at.desc()).limit(limit).offset(offset)
    if automation_id is not None:
        q = q.where(DMLog.automation_id == automation_id)
    if status:
        q = q.where(DMLog.status == status)
    result = await db.execute(q)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Posts (proxy to Instagram service — useful for the UI's post selector)
# ---------------------------------------------------------------------------


@router.get("/posts")
async def list_posts():
    """Return the authenticated user's recent posts (for building automations)."""
    try:
        if settings.integration_mode == "official":
            posts = await instagram_api_service.list_recent_media(20)
        else:
            posts = await instagram_service.get_user_posts(20)
        return posts
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=StatusOut)
async def get_status():
    from app.main import scheduler  # imported here to avoid circular import

    if settings.integration_mode == "official":
        logged_in = instagram_api_service.configured
        username = settings.instagram_username
    else:
        logged_in = instagram_service.context is not None
        username = instagram_service.username if logged_in else None

    next_poll = None
    scheduler_running = False
    try:
        scheduler_running = scheduler.running
        jobs = scheduler.get_jobs()
        if jobs:
            next_run = jobs[0].next_run_time
            next_poll = next_run.isoformat() if next_run else None
    except Exception:
        pass

    return StatusOut(
        logged_in=logged_in,
        username=username,
        scheduler_running=scheduler_running,
        next_poll=next_poll,
    )


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------


@router.post("/poll/trigger")
async def trigger_poll():
    """Manually kick off a poll cycle without waiting for the scheduler."""
    if settings.integration_mode == "official":
        raise HTTPException(
            status_code=400,
            detail="Polling is disabled in official API mode. Use the Instagram webhook instead.",
        )

    from app.engine import run_poll_cycle

    try:
        summaries = await run_poll_cycle()
        return {"status": "ok", "summaries": summaries}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Instagram webhooks (official API path)
# ---------------------------------------------------------------------------


def _extract_comment_events(payload: dict) -> list[dict]:
    events: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            value = change.get("value", {}) or {}
            media = value.get("media", {}) or {}
            user = value.get("from", {}) or {}

            comment_id = str(value.get("comment_id") or value.get("id") or "").strip()
            comment_text = str(value.get("text") or value.get("message") or "").strip()
            media_id = str(value.get("media_id") or media.get("id") or "").strip()
            username = str(
                value.get("username")
                or user.get("username")
                or value.get("sender_name")
                or ""
            ).strip()
            user_id = str(user.get("id") or value.get("user_id") or username or comment_id).strip()

            if not comment_id or not comment_text:
                continue

            events.append(
                {
                    "comment_id": comment_id,
                    "comment_text": comment_text,
                    "media_id": media_id,
                    "username": username or user_id,
                    "user_id": user_id,
                }
            )
    return events


async def _process_comment_event(db: AsyncSession, event: dict) -> dict:
    result = await db.execute(select(Automation).where(Automation.is_active == True))
    automations = list(result.scalars().all())

    matches: list[dict] = []
    for automation in automations:
        if automation.keyword.lower() not in event["comment_text"].lower():
            continue

        target_post_ids = automation.post_id_list()
        if target_post_ids and event["media_id"] and event["media_id"] not in target_post_ids:
            continue

        duplicate = await db.execute(
            select(DMLog).where(
                DMLog.automation_id == automation.id,
                DMLog.comment_id == event["comment_id"],
            )
        )
        if duplicate.scalar_one_or_none() is not None:
            matches.append({"automation_id": automation.id, "status": "duplicate"})
            continue

        message = automation.dm_message.replace("{username}", event["username"])
        status = "failed"
        reply_result = None

        try:
            reply_result = await instagram_api_service.send_private_reply(
                event["comment_id"], message
            )
            status = "sent"
        except Exception as exc:
            logger.exception("Private reply failed for comment %s: %s", event["comment_id"], exc)

        db.add(
            DMLog(
                automation_id=automation.id,
                user_id=event["user_id"],
                username=event["username"],
                comment_id=event["comment_id"],
                comment_text=event["comment_text"],
                media_id=event["media_id"] or "",
                status=status,
            )
        )
        await db.commit()

        if status == "sent":
            db.add(
                Lead(
                    automation_id=automation.id,
                    user_id=event["user_id"],
                    username=event["username"],
                    comment_text=event["comment_text"],
                    media_id=event["media_id"] or "",
                )
            )
            try:
                await db.commit()
            except Exception:
                await db.rollback()

        matches.append(
            {
                "automation_id": automation.id,
                "status": status,
                "reply": reply_result,
            }
        )

    return {"comment_id": event["comment_id"], "matches": matches}


@router.get("/webhooks/instagram")
async def verify_instagram_webhook(request: Request):
    query_params = request.query_params
    hub_mode = query_params.get("hub.mode") or query_params.get("hub_mode")
    hub_verify_token = query_params.get("hub.verify_token") or query_params.get(
        "hub_verify_token"
    )
    hub_challenge = query_params.get("hub.challenge") or query_params.get("hub_challenge")

    challenge = instagram_api_service.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return PlainTextResponse(challenge)


@router.post("/webhooks/instagram")
async def receive_instagram_webhook(request: Request):
    raw_body = await request.body()
    if not instagram_api_service.verify_signature(
        raw_body, request.headers.get("X-Hub-Signature-256")
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    payload = await request.json()
    events = _extract_comment_events(payload)
    if not events:
        return {"status": "ignored", "matched": 0}

    results = []
    async with AsyncSessionLocal() as db:
        for event in events:
            results.append(await _process_comment_event(db, event))

    return {"status": "ok", "matched": len(results), "results": results}
