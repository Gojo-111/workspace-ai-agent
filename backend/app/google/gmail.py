# backend/app/google/gmail.py
import asyncio
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
from uuid import UUID

from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.google.client_factory import get_google_client


def _build_email(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    is_html: bool = False,
) -> str:
    """
    Build an RFC 2822 email message from parts.

    Returns a base64url-encoded string suitable for the Gmail API.
    """
    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc

    # Attach both plain and HTML versions if HTML is requested
    if is_html:
        # Plain text fallback
        plain_part = MIMEText(body, "plain")
        html_part = MIMEText(body, "html")
        msg.attach(plain_part)
        msg.attach(html_part)
    else:
        msg.attach(MIMEText(body, "plain"))

    # Encode to base64url
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return raw


async def search(
    db: AsyncSession,
    user_id: UUID,
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Search Gmail messages matching a query.

    Returns a list of message summaries with id, threadId, and snippet.
    """
    client = await get_google_client(db, user_id, "gmail", "v1")

    def _search() -> dict:
        return (
            client.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=max_results,
            )
            .execute()
        )

    try:
        result = await asyncio.to_thread(_search)
        messages = result.get("messages", [])
        # The list only returns id and threadId; we may optionally get more details
        # by calling get for each, but that would be expensive. Return summaries.
        return messages
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError("Gmail service not available") from exc
        raise


async def get(
    db: AsyncSession,
    user_id: UUID,
    message_id: str,
    format: str = "full",
) -> dict:
    """
    Fetch a full Gmail message by ID.

    format can be "full", "metadata", "minimal", or "raw".
    Returns the full message object from the API.
    """
    client = await get_google_client(db, user_id, "gmail", "v1")

    def _get() -> dict:
        return (
            client.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format=format,
            )
            .execute()
        )

    try:
        return await asyncio.to_thread(_get)
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Gmail message not found: {message_id}") from exc
        raise


async def create_draft(
    db: AsyncSession,
    user_id: UUID,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    is_html: bool = False,
) -> dict:
    """
    Create a draft email in the user's Gmail.

    Returns the draft metadata including draft ID and message ID.
    """
    client = await get_google_client(db, user_id, "gmail", "v1")

    raw_message = _build_email(to, subject, body, cc, bcc, is_html)

    draft_body = {
        "message": {
            "raw": raw_message,
        }
    }

    def _create() -> dict:
        return (
            client.users()
            .drafts()
            .create(userId="me", body=draft_body)
            .execute()
        )

    try:
        draft = await asyncio.to_thread(_create)
        return {
            "draft_id": draft.get("id"),
            "message_id": draft.get("message", {}).get("id"),
            "thread_id": draft.get("message", {}).get("threadId"),
        }
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError("Gmail service not available") from exc
        raise


async def send_draft(
    db: AsyncSession,
    user_id: UUID,
    draft_id: str,
) -> dict:
    """
    Send an existing draft email.

    Returns the sent message metadata.
    """
    client = await get_google_client(db, user_id, "gmail", "v1")

    def _send() -> dict:
        return (
            client.users()
            .drafts()
            .send(userId="me", body={"id": draft_id})
            .execute()
        )

    try:
        sent = await asyncio.to_thread(_send)
        return {
            "message_id": sent.get("id"),
            "thread_id": sent.get("threadId"),
        }
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Draft not found: {draft_id}") from exc
        raise


async def send_message(
    db: AsyncSession,
    user_id: UUID,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    is_html: bool = False,
) -> dict:
    """
    Send an email directly (without creating a draft first).

    This is useful for quick sends, but note that the policy check
    should still require confirmation. Returns the sent message metadata.
    """
    client = await get_google_client(db, user_id, "gmail", "v1")

    raw_message = _build_email(to, subject, body, cc, bcc, is_html)

    message_body = {
        "raw": raw_message,
    }

    def _send() -> dict:
        return (
            client.users()
            .messages()
            .send(userId="me", body=message_body)
            .execute()
        )

    try:
        sent = await asyncio.to_thread(_send)
        return {
            "message_id": sent.get("id"),
            "thread_id": sent.get("threadId"),
        }
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError("Gmail service not available") from exc
        raise