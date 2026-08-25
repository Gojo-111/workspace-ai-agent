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


def _extract_paragraphs(document: dict) -> list[dict]:
    """
    Number every paragraph in the doc and record where it actually sits.

    The number and text are what the caller (agent/LLM) works with. The
    start/end index are Docs-internal and only used inside this file, right
    after a fresh fetch, so they're never stale.

    Non-paragraph elements (tables, section breaks) are skipped, same as
    `_extract_text`, so this numbering is our own scheme, not a 1:1 match
    with what the Docs UI would show you.
    """
    paragraphs = []
    number = 0

    for element in document.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")

        if not paragraph:
            continue

        number += 1
        text = "".join(
            run.get("textRun", {}).get("content", "")
            for run in paragraph.get("elements", [])
        )

        paragraphs.append(
            {
                "number": number,
                "text": text,
                "start_index": element["startIndex"],
                "end_index": element["endIndex"],
            }
        )

    return paragraphs


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
    """
    Fetch a Google Doc's title, plain text, and a numbered paragraph list.

    The paragraph list is what you use with `update(mode="replace_paragraph",
    paragraph_number=...)` and similar, pick a number from here, don't guess
    one.
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

    return {
        "document_id": document_id,
        "title": document.get("title", ""),
        "content": _extract_text(document),
        "paragraphs": [
            {"number": p["number"], "text": p["text"]}
            for p in _extract_paragraphs(document)
        ],
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


UpdateMode = Literal[
    "append",
    "replace",
    "replace_paragraph",
    "insert_before_paragraph",
    "insert_after_paragraph",
]


async def update(
    db: AsyncSession,
    user_id: UUID,
    document_id: str,
    content: str,
    mode: UpdateMode = "append",
    paragraph_number: int | None = None,
) -> dict:
    """
    Update a Google Doc's content.

    Modes:
    - "append": add content to the end of the doc.
    - "replace": clear the whole body, then insert content.
    - "replace_paragraph": swap the text of one paragraph, keeps its spot
      in the doc. Needs `paragraph_number`.
    - "insert_before_paragraph" / "insert_after_paragraph": add a new
      paragraph right before/after an existing one. Needs
      `paragraph_number`.

    Always re-fetches the doc first to get current, correct indices, Docs
    indices shift on every edit, so a number from an earlier `get()` call is
    still safe to use (it's just a paragraph count), but a raw index never
    would be.
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

    paragraph_modes = {
        "replace_paragraph",
        "insert_before_paragraph",
        "insert_after_paragraph",
    }

    target = None

    if mode in paragraph_modes:
        if paragraph_number is None:
            raise ValueError(f"paragraph_number is required for mode '{mode}'")

        paragraphs = _extract_paragraphs(document)
        target = next(
            (p for p in paragraphs if p["number"] == paragraph_number),
            None,
        )

        if target is None:
            raise ValueError(
                f"Paragraph {paragraph_number} doesn't exist, "
                f"this doc has {len(paragraphs)} paragraphs"
            )

    requests: list[dict] = []

    if mode == "replace":
        end_index = _document_end_index(document)

        if end_index > 1:
            requests.append(
                {
                    "deleteContentRange": {
                        "range": {"startIndex": 1, "endIndex": end_index}
                    }
                }
            )

        requests.append(
            {"insertText": {"location": {"index": 1}, "text": content}}
        )

    elif mode == "append":
        end_index = _document_end_index(document)

        requests.append(
            {
                "insertText": {
                    "location": {"index": end_index},
                    "text": content,
                }
            }
        )

    elif mode == "replace_paragraph":
        # endIndex includes the paragraph's trailing newline, we delete up
        # to just before it so the paragraph itself stays intact, only its
        # text changes.
        inner_end = target["end_index"] - 1

        if inner_end > target["start_index"]:
            requests.append(
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": target["start_index"],
                            "endIndex": inner_end,
                        }
                    }
                }
            )

        requests.append(
            {
                "insertText": {
                    "location": {"index": target["start_index"]},
                    "text": content,
                }
            }
        )

    elif mode == "insert_before_paragraph":
        requests.append(
            {
                "insertText": {
                    "location": {"index": target["start_index"]},
                    "text": f"{content}\n",
                }
            }
        )

    elif mode == "insert_after_paragraph":
        requests.append(
            {
                "insertText": {
                    "location": {"index": target["end_index"]},
                    "text": f"{content}\n",
                }
            }
        )

    else:
        raise ValueError(f"Unknown update mode: {mode}")

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
        "paragraph_number": paragraph_number,
    }