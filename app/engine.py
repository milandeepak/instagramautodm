"""
Automation engine — the brain of the system.

Runs on a scheduler tick (every POLL_INTERVAL_SECONDS):
1. Load all active automations from DB
2. For each automation, determine which posts to watch
3. Fetch recent comments on those posts
4. For each comment:
   a. Skip if already processed (dedup via dm_log)
   b. Check if comment text contains the keyword (case-insensitive)
   c. Optionally verify commenter follows you (follow-gate)
   d. Send DM
   e. Log result + record lead
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import AsyncSessionLocal, Automation, DMLog, Lead
from app.instagram_service import instagram_service

logger = logging.getLogger(__name__)


async def _is_already_processed(session, automation_id: int, comment_id: str) -> bool:
    """Check if this comment has already been processed for this automation."""
    result = await session.execute(
        select(DMLog).where(
            DMLog.automation_id == automation_id,
            DMLog.comment_id == comment_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _log_dm(
    session,
    automation_id: int,
    user_id: str,
    username: str,
    comment_id: str,
    comment_text: str,
    media_id: str,
    status: str,
) -> None:
    log_entry = DMLog(
        automation_id=automation_id,
        user_id=user_id,
        username=username,
        comment_id=comment_id,
        comment_text=comment_text,
        media_id=media_id,
        status=status,
    )
    session.add(log_entry)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.debug(
            "Duplicate dm_log entry, skipping insert (automation=%d user=%s)",
            automation_id,
            user_id,
        )


async def _record_lead(
    session,
    automation_id: int,
    user_id: str,
    username: str,
    comment_text: str,
    media_id: str,
) -> None:
    lead = Lead(
        automation_id=automation_id,
        user_id=user_id,
        username=username,
        comment_text=comment_text,
        media_id=media_id,
    )
    session.add(lead)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()


async def process_automation(automation: Automation, posts: list[dict]) -> dict:
    """
    Process one automation against the given list of posts.
    Returns a summary dict with counts.
    """
    summary = {"automation_id": automation.id, "checked": 0, "sent": 0, "skipped": 0}

    # Determine which posts to watch
    target_post_ids = automation.post_id_list()
    if target_post_ids:
        posts_to_check = [p for p in posts if p["media_id"] in target_post_ids]
    else:
        posts_to_check = posts  # watch all recent posts

    for post in posts_to_check:
        media_id = post["media_id"]
        comments = await instagram_service.get_media_comments(media_id, 100)

        for comment in comments:
            summary["checked"] += 1
            comment_text: str = comment["text"]
            user_id: str = comment["user_id"]
            username: str = comment["username"]
            comment_id: str = comment["comment_id"]

            # Case-insensitive keyword match
            if automation.keyword.lower() not in comment_text.lower():
                continue

            async with AsyncSessionLocal() as session:
                # Dedup — never DM the same user for the same automation twice
                if await _is_already_processed(session, automation.id, comment_id):
                    logger.debug(
                        "Already processed comment %s for automation %d — skipping",
                        comment_id,
                        automation.id,
                    )
                    continue

                # Follow-gate check
                if automation.require_follow:
                    follows = await instagram_service.check_user_follows_me(user_id)
                    if not follows:
                        logger.info(
                            "User @%s does not follow — skipping DM (automation %d)",
                            username,
                            automation.id,
                        )
                        # Don't log as processed — check again next cycle in case they follow later
                        summary["skipped"] += 1
                        continue

                # Personalise the message
                message = automation.dm_message.replace("{username}", username)

                # Send DM
                sent = await instagram_service.send_dm(user_id, message)

                status = "sent" if sent else "skipped_rate_limit"
                await _log_dm(
                    session,
                    automation_id=automation.id,
                    user_id=user_id,
                    username=username,
                    comment_id=comment_id,
                    comment_text=comment_text,
                    media_id=media_id,
                    status=status,
                )

                if sent:
                    await _record_lead(
                        session,
                        automation_id=automation.id,
                        user_id=user_id,
                        username=username,
                        comment_text=comment_text,
                        media_id=media_id,
                    )
                    summary["sent"] += 1
                    logger.info(
                        "DM sent to @%s (automation: %s, keyword: %s)",
                        username,
                        automation.name,
                        automation.keyword,
                    )
                else:
                    summary["skipped"] += 1

    return summary


async def run_poll_cycle() -> list[dict]:
    """
    Main poll cycle — called by the scheduler every POLL_INTERVAL_SECONDS.
    Returns list of per-automation summaries.
    """
    logger.info("Starting poll cycle...")
    summaries = []

    # Fetch active automations
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Automation).where(Automation.is_active == True)
        )
        automations: list[Automation] = list(result.scalars().all())

    if not automations:
        logger.info("No active automations — nothing to do.")
        return []

    # Fetch recent posts once, reuse for all automations
    posts = await instagram_service.get_user_posts(12)
    if not posts:
        logger.warning("Could not fetch posts — skipping cycle.")
        return []

    logger.info(
        "Found %d active automation(s), checking %d post(s)",
        len(automations),
        len(posts),
    )

    for automation in automations:
        try:
            summary = await process_automation(automation, posts)
            summaries.append(summary)
            logger.info(
                "Automation '%s': checked=%d sent=%d skipped=%d",
                automation.name,
                summary["checked"],
                summary["sent"],
                summary["skipped"],
            )
        except Exception as exc:
            logger.error(
                "Error processing automation %d (%s): %s",
                automation.id,
                automation.name,
                exc,
            )

    return summaries
