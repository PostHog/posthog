"""
Slack notifications for legal document lifecycle events.

Uses a Slack incoming webhook URL (SLACK_LEGAL_DOCUMENTS_WEBHOOK_URL) bound to
a single channel at creation time — no bot token, no per-channel config, no
install flow. The slack-app product handles per-org Slack integrations; this
is intentionally separate — we own both sides.

Every public function is safe to call unconditionally: if the webhook isn't
configured or the call fails, we log and move on so the customer's submit/sign
flow never breaks because Slack is flaky.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

import requests
import structlog

from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10


def _post(text: str, blocks: list[dict[str, Any]]) -> None:
    webhook_url = settings.SLACK_LEGAL_DOCUMENTS_WEBHOOK_URL
    if not webhook_url:
        logger.info("slack_legal_documents_not_configured", reason="missing webhook URL")
        return
    try:
        response = requests.post(
            webhook_url,
            json={"text": text, "blocks": blocks},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            logger.warning(
                "slack_legal_documents_post_non_2xx",
                status=response.status_code,
                body=response.text[:500],
            )
            capture_exception(
                RuntimeError(f"Slack webhook returned {response.status_code}: {response.text[:200]}"),
            )
    except requests.RequestException as exc:
        logger.exception("slack_legal_documents_post_failed", error=str(exc))
        capture_exception(exc)


def _fields_block(fields: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": f"*{label}*\n{value or '_unknown_'}"} for label, value in fields],
    }


def notify_submitted(
    *,
    document_type: str,
    company_name: str,
    representative_email: str,
    pandadoc_document_id: str | None,
) -> None:
    header = f":scroll: New {document_type} submitted"
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": header, "emoji": True}},
        _fields_block(
            [
                ("Company", company_name),
                ("Signer email", representative_email),
            ]
        ),
    ]
    if pandadoc_document_id:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open in PandaDoc", "emoji": True},
                        "url": f"https://app.pandadoc.com/a/#/documents/{pandadoc_document_id}",
                    }
                ],
            }
        )
    _post(header, blocks)


def notify_signed(
    *,
    document_type: str,
    company_name: str,
    pandadoc_document_id: str | None,
) -> None:
    header = f":white_check_mark: {document_type} signed"
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": header, "emoji": True}},
        _fields_block([("Company", company_name)]),
    ]
    if pandadoc_document_id:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open in PandaDoc", "emoji": True},
                        "url": f"https://app.pandadoc.com/a/#/documents/{pandadoc_document_id}",
                    }
                ],
            }
        )
    _post(header, blocks)
