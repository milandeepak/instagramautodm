"""
Pydantic schemas for request/response validation.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Automation schemas
# ---------------------------------------------------------------------------


class AutomationCreate(BaseModel):
    name: str = Field(..., max_length=120, description="Human-readable label")
    keyword: str = Field(
        ..., max_length=100, description="Keyword to match in comments"
    )
    dm_message: str = Field(
        ..., description="DM text; use {username} for personalisation"
    )
    require_follow: bool = Field(
        True, description="Require commenter to follow you first"
    )
    post_ids: Optional[str] = Field(
        None,
        description="Comma-separated Instagram media IDs to watch. Leave blank to watch all recent posts.",
    )
    is_active: bool = Field(True)


class AutomationUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    keyword: Optional[str] = Field(None, max_length=100)
    dm_message: Optional[str] = None
    require_follow: Optional[bool] = None
    post_ids: Optional[str] = None
    is_active: Optional[bool] = None


class AutomationOut(BaseModel):
    id: int
    name: str
    keyword: str
    dm_message: str
    require_follow: bool
    post_ids: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Lead schemas
# ---------------------------------------------------------------------------


class LeadOut(BaseModel):
    id: int
    automation_id: int
    user_id: str
    username: str
    comment_text: str
    media_id: str
    dm_sent_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# DMLog schemas
# ---------------------------------------------------------------------------


class DMLogOut(BaseModel):
    id: int
    automation_id: int
    user_id: str
    username: str
    comment_id: str
    comment_text: str
    media_id: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Status / misc
# ---------------------------------------------------------------------------


class StatusOut(BaseModel):
    logged_in: bool
    username: Optional[str]
    scheduler_running: bool
    next_poll: Optional[str]
