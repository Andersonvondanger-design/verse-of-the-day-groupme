#!/usr/bin/env python3
"""
Daily Verse of the Day poster for GroupMe.

Reads:
- YVP_APP_KEY from environment (YouVersion app key)
- GROUPME_BOT_ID from environment (GroupMe bot ID)

Uses:
- https://api.youversion.com/v1/verse-of-the-days/{day}
- https://api.youversion.com/v1/bibles/59/passages/{passage_id}?format=text
- https://api.groupme.com/v3/bots/post
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

YOUVERSION_BASE_URL = "https://api.youversion.com/v1"
GROUPME_BOT_POST_URL = "https://api.groupme.com/v3/bots/post"
DEFAULT_BIBLE_VERSION_ID = 59
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3


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


def get_day_of_year() -> int:
    """Get today's day of year (1-366)."""
    return datetime.utcnow().timetuple().tm_yday


def build_youversion_headers(app_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-YouVersion-Api-Key": app_key,
        "X-YV-App-Key": app_key,
    }


def find_first_value(data: Any, keys: tuple[str, ...]) -> Any:
    """Recursively search for the first non-empty value matching any of the keys."""
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] not in (None, "", [], {}):
                return data[key]
        for value in data.values():
            found = find_first_value(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_first_value(item, keys)
            if found is not None:
                return found
    return None


def request_json(
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
    method: str = "GET",
) -> Any:
    """Make an API request with retry logic for rate limiting."""
    attempts = 0
    while attempts < MAX_RETRIES:
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout as exc:
            raise RuntimeError(f"Request timed out while calling {url}") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 1
            logging.warning(
                "Rate limited. Sleeping for %s seconds before retry %s/%s.",
                wait_seconds,
                attempts + 1,
                MAX_RETRIES,
            )
            time.sleep(wait_seconds)
            attempts += 1
            continue

        if response.status_code >= 400:
            snippet = response.text[:500].replace("\n", " ")
            raise RuntimeError(f"HTTP {response.status_code} from {url}: {snippet}")

        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"API returned invalid JSON from {url}: {response.text[:500]}"
            ) from exc

    raise RuntimeError(f"API request failed after {MAX_RETRIES} attempts: {url}")


def get_daily_passage_id(app_key: str, day: int) -> str:
    """Fetch the daily passage ID from YouVersion."""
    url = f"{YOUVERSION_BASE_URL}/verse-of-the-days/{day}"
    logging.info("Calling %s", url)
    payload = request_json(url, headers=build_youversion_headers(app_key))
    logging.info("Response: %s", payload)
    
    passage_id = find_first_value(payload, ("passage_id", "passageId", "id"))
    if passage_id is None:
        raise RuntimeError(f"Could not find passage_id in response from {url}: {payload}")
    logging.info("Retrieved passage_id: %s", passage_id)
    return str(passage_id)


def get_daily_verse_text(app_key: str, version_id: int, passage_id: str) -> tuple[str, str]:
    """Fetch the verse text and reference from YouVersion."""
    url = f"{YOUVERSION_BASE_URL}/bibles/{version_id}/passages/{passage_id}"
    logging.info("Calling %s", url)
    payload = request_json(
        url,
        headers=build_youversion_headers(app_key),
        params={"format": "text"},
    )
    logging.info("Response: %s", payload)

    verse_text = find_first_value(payload, ("text", "content", "verse_text", "passage_text"))
    reference = find_first_value(payload, ("reference", "citation", "verse_reference", "passage_reference"))

    if verse_text is None:
        raise RuntimeError(f"Could not find verse text in response from {url}: {payload}")
    if reference is None:
        reference = "Daily Verse"

    return str(verse_text).strip(), str(reference).strip()


def build_groupme_message(verse_text: str, reference: str) -> str:
    """Format the verse as a GroupMe message."""
    cleaned_text = verse_text.strip().replace("\r\n", "\n").replace("\r", "\n")
    return (
        "📖 Verse of the Day\n"
        f'"{cleaned_text}"\n'
        f"— {reference} (English Standard Version)\n"
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

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 1
        logging.warning("GroupMe rate limited. Waiting %s seconds before retrying.", wait_seconds)
        time.sleep(wait_seconds)
        response = requests.post(
            GROUPME_BOT_POST_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

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
        app_key = get_required_env("YVP_APP_KEY")
        bot_id = get_required_env("GROUPME_BOT_ID")

        day = get_day_of_year()
        logging.info("Fetching Verse of the Day for day %s.", day)

        passage_id = get_daily_passage_id(app_key, day)
        verse_text, reference = get_daily_verse_text(app_key, DEFAULT_BIBLE_VERSION_ID, passage_id)
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
