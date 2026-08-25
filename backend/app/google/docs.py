import asyncio
from typing import Literal
from uuid import UUID

from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.google.client_factory import get_google_client


def _extract_text(document: dict) -> str:
    """
    Pull plain text out of a Google Doc's structural content.

    Docs stores content as a list of paragraphs, each made of text runs.
    This just walks that structure and joins the text together. Anything
    that isn't a plain paragraph (tables, images) is skipped for the MVP.
    """
    text_parts = []

    for element in document.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")

        if not paragraph:
            continue

        for run in paragraph.get("elements", []):
            text_run = run.get("textRun")

            if text_run:
                text_parts.append(text_run.get("content", ""))

    return "".join(text_parts)


def _document_end_index(document: dict) -> int:
    """
    Find the last insertable index in the document body.

    Docs won't let you insert or delete right at the very end of a segment,
    you have to stop one short of it. This finds that boundary.
    """
    content = document.get("body", {}).get("content", [])

    if not content:
        return 1

    return content[-1].get("endIndex", 1) - 1


async def get(
    db: AsyncSession,
    user_id: UUID,
    document_id: str,
) -> dict:
    """Fetch a Google Doc's title and plain text content."""
    client = await get_google_client(db, user_id, "docs", "v1")

    def _get() -> dict:
        return client.documents().get(documentId=document_id).execute()

    try:
        document = await asyncio.to_thread(_get)
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Google Doc not found: {document_id}") from exc
        raise

    return {
        "document_id": document_id,
        "title": document.get("title", ""),
        "content": _extract_text(document),
    }


async def create(
    db: AsyncSession,
    user_id: UUID,
    title: str,
    content: str = "",
) -> dict:
    """
    Create a new Google Doc.

    If content is given, it's inserted right after creation in a second
    call, since the create endpoint only accepts a title, not a body.
    """
    client = await get_google_client(db, user_id, "docs", "v1")

    def _create() -> dict:
        return client.documents().create(body={"title": title}).execute()

    document = await asyncio.to_thread(_create)
    document_id = document["documentId"]

    if content:
        def _insert() -> dict:
            return (
                client.documents()
                .batchUpdate(
                    documentId=document_id,
                    body={
                        "requests": [
                            {
                                "insertText": {
                                    "location": {"index": 1},
                                    "text": content,
                                }
                            }
                        ]
                    },
                )
                .execute()
            )

        await asyncio.to_thread(_insert)

    return {
        "document_id": document_id,
        "title": title,
    }


async def update(
    db: AsyncSession,
    user_id: UUID,
    document_id: str,
    content: str,
    mode: Literal["append", "replace"] = "append",
) -> dict:
    """
    Update a Google Doc's content.

    "append" adds content to the end. "replace" clears the whole body first,
    then inserts. Both are single batchUpdate calls, Docs applies a list of
    requests atomically, so there's no risk of a half-applied edit.
    """
    client = await get_google_client(db, user_id, "docs", "v1")

    def _get() -> dict:
        return client.documents().get(documentId=document_id).execute()

    try:
        document = await asyncio.to_thread(_get)
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Google Doc not found: {document_id}") from exc
        raise

    end_index = _document_end_index(document)
    requests: list[dict] = []

    if mode == "replace" and end_index > 1:
        requests.append(
            {
                "deleteContentRange": {
                    "range": {"startIndex": 1, "endIndex": end_index}
                }
            }
        )
        insert_index = 1
    else:
        insert_index = end_index

    requests.append(
        {
            "insertText": {
                "location": {"index": insert_index},
                "text": content,
            }
        }
    )

    def _update() -> dict:
        return (
            client.documents()
            .batchUpdate(documentId=document_id, body={"requests": requests})
            .execute()
        )

    await asyncio.to_thread(_update)

    return {
        "document_id": document_id,
        "mode": mode,
    }