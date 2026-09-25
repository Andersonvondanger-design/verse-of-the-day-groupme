#!/usr/bin/env python3
"""
Daily Verse of the Day poster for GroupMe.

Uses:
- https://bible-api.com/verse-of-the-day (free, no API key needed)
- https://api.groupme.com/v3/bots/post

Environment variables:
- GROUPME_BOT_ID: Your GroupMe bot ID
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

BIBLE_API_URL = "https://bible-api.com/verse-of-the-day"
GROUPME_BOT_POST_URL = "https://api.groupme.com/v3/bots/post"
REQUEST_TIMEOUT_SECONDS = 15


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def request_json(url: str) -> Any:
    """Make an API request."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(f"Request timed out while calling {url}") from exc

    if response.status_code >= 400:
        snippet = response.text[:500].replace("\n", " ")
        raise RuntimeError(f"HTTP {response.status_code} from {url}: {snippet}")

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"API returned invalid JSON from {url}: {response.text[:500]}"
        ) from exc


def get_daily_verse() -> tuple[str, str]:
    """Fetch the daily verse from Bible-API."""
    logging.info("Calling %s", BIBLE_API_URL)
    payload = request_json(BIBLE_API_URL)
    logging.info("Response: %s", payload)

    verse_text = payload.get("text")
    reference = payload.get("reference")

    if verse_text is None:
        raise RuntimeError(f"Could not find verse text in response: {payload}")
    if reference is None:
        reference = "Daily Verse"

    return str(verse_text).strip(), str(reference).strip()


def build_groupme_message(verse_text: str, reference: str) -> str:
    """Format the verse as a GroupMe message."""
    cleaned_text = verse_text.strip().replace("\r\n", "\n").replace("\r", "\n")
    return (
        "📖 Verse of the Day\n"
        f'"{cleaned_text}"\n'
        f"— {reference}\n"
        "Have a blessed day! 🙏"
    )


def post_to_groupme(bot_id: str, message: str) -> None:
    """Post the message to GroupMe."""
    payload = {"bot_id": bot_id, "text": message}

    try:
        response = requests.post(
            GROUPME_BOT_POST_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("GroupMe request timed out while posting the verse.") from exc

    if response.status_code >= 400:
        snippet = response.text[:500].replace("\n", " ")
        raise RuntimeError(f"GroupMe API returned HTTP {response.status_code}: {snippet}")

    response_json = response.json()
    if response_json.get("meta", {}).get("code") not in (200, 201, 202):
        raise RuntimeError(f"GroupMe API rejected the post: {response_json}")

    logging.info("Verse successfully posted to GroupMe.")


def main() -> int:
    configure_logging()

    try:
        bot_id = get_required_env("GROUPME_BOT_ID")
        logging.info("Fetching Verse of the Day.")
        verse_text, reference = get_daily_verse()
        message = build_groupme_message(verse_text, reference)
        logging.info("Posting message to GroupMe:")
        logging.info(message)
        post_to_groupme(bot_id, message)
        return 0
    except Exception as exc:  # pragma: no cover - top-level app error handling
        logging.exception("Failed to post the Verse of the Day: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
