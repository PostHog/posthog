"""Turns a short idea spec into a complete draft workflow: trigger, waits, designed emails and a goal."""

import html
from datetime import datetime
from typing import Any

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team

from products.workflows.backend.facade.contracts import IdeaDraftSpec, IdeaEmail, NewWorkflowIdea

logger = structlog.get_logger(__name__)

UNSUBSCRIBE_FOOTER = (
    '<p style="text-align: center; font-size: 12px; color: #6b7280;">'
    "You're getting this email because you have an account with {sender}. "
    '<a href="{{{{ unsubscribe_url }}}}" style="color: #6b7280; text-decoration: underline;">Unsubscribe</a>'
    "</p>"
)
BUTTON_COLOR = "#111827"
# Stands in for the project's site until a person enters it, and is swapped out before the draft is saved.
SITE_PLACEHOLDER = "https://your-website.example"


def build_idea_definition(spec: IdeaDraftSpec) -> dict[str, Any]:
    if len(spec.waits) != len(spec.emails) or not spec.emails:
        raise ValueError("Each email needs exactly one wait before it.")
    actions: list[dict[str, Any]] = [
        {
            "id": "trigger_node",
            "name": "Trigger",
            "type": "trigger",
            "description": "",
            "config": {
                "type": "event",
                "filters": {
                    "events": [_event(spec.trigger_event)],
                    # Only people with an address can get the emails, so others never enter.
                    "properties": [{"key": "email", "type": "person", "operator": "is_set", "value": "is_set"}],
                    "filter_test_accounts": True,
                },
            },
        }
    ]
    for index, (wait, email) in enumerate(zip(spec.waits, spec.emails), start=1):
        actions.append(
            {
                "id": f"wait_{index}",
                "name": f"Wait {wait}",
                "type": "delay",
                "description": "",
                "config": {"delay_duration": wait},
            }
        )
        actions.append(_email_action(index, email, spec))
    actions.append(
        {"id": "exit_node", "name": "Exit", "type": "exit", "description": "", "config": {"reason": "Default exit"}}
    )
    ids = [action["id"] for action in actions]
    return {
        "trigger_masking": {"hash": "{person.id}", "ttl": spec.once_per_person_days * 24 * 60 * 60},
        "exit_condition": "exit_on_conversion",
        "conversion": {
            "window_minutes": None,
            "events": [{"filters": {"events": [_event(name) for name in spec.goal_events]}}],
            "filters": [],
        },
        "actions": actions,
        "edges": [{"from": a, "to": b, "type": "continue"} for a, b in zip(ids, ids[1:])],
    }


def new_idea_from_draft(
    *,
    key: str,
    title: str,
    rationale: str,
    value_tier: str,
    evidence: dict[str, Any],
    spec: IdeaDraftSpec,
) -> NewWorkflowIdea:
    """An idea whose definition is built from `spec`, with the numbers the idea card shows added to its evidence."""
    reach = int(evidence.get("reachable_people") or 0)
    return NewWorkflowIdea(
        key=key,
        title=title,
        rationale=rationale,
        value_tier=value_tier,
        definition=build_idea_definition(spec),
        evidence={
            **evidence,
            "trigger_event": spec.trigger_event,
            "goal_events": spec.goal_events,
            "site_url": spec.site_url,
            "waits": spec.waits,
            "once_per_person_days": spec.once_per_person_days,
            # Everyone gets the first email, and most of them have still not reached the goal by the next one.
            "emails_per_month": round(reach * (1 + 0.9 * (len(spec.emails) - 1))),
        },
    )


def _event(name: str) -> dict[str, str]:
    return {"id": name, "name": name, "type": "events"}


def _button_url(spec: IdeaDraftSpec, email: IdeaEmail) -> str:
    base = (spec.site_url or SITE_PLACEHOLDER).rstrip("/")
    return f"{base}{email.button_path}"


def _email_action(index: int, email: IdeaEmail, spec: IdeaDraftSpec) -> dict[str, Any]:
    url = _button_url(spec, email)
    footer = (spec.footer_template or UNSUBSCRIBE_FOOTER).format(sender=html.escape(spec.sender_name))
    return {
        "id": f"email_{index}",
        "name": f"Email {index}",
        "type": "function_email",
        "description": email.subject,
        "config": {
            "template_id": "template-email",
            "utm_tags_enabled": True,
            "utm_params": {"utm_source": "posthog", "utm_medium": "email", "utm_campaign": spec.campaign, **spec.utm},
            "inputs": {
                "email": {
                    "templating": "liquid",
                    "value": {
                        "to": {"email": "{{ person.properties.email }}", "name": ""},
                        "from": {"name": spec.sender_name},
                        "subject": email.subject,
                        "preheader": email.preheader,
                        "html": _render_html(email, url, footer),
                        "text": _render_text(email, url),
                        "design": _render_design(email, url, footer),
                    },
                }
            },
        },
    }


def _render_html(email: IdeaEmail, url: str, footer: str) -> str:
    paragraphs = "".join(
        f'<p style="margin: 0 0 16px; font-size: 15px; line-height: 1.6; color: #374151;">{html.escape(p)}</p>'
        for p in email.paragraphs
    )
    button = (
        f'<p style="margin: 24px 0;"><a href="{html.escape(url)}" style="display: inline-block; padding: 12px 22px; '
        f"background: {BUTTON_COLOR}; color: #ffffff; border-radius: 6px; font-weight: 600; font-size: 15px; "
        f'text-decoration: none;">{html.escape(email.button_text)}</a></p>'
        if url
        else ""
    )
    return (
        "<!doctype html><html><body style=\"margin: 0; background: #f9fafb; font-family: -apple-system, 'Segoe UI', "
        'Helvetica, Arial, sans-serif;">'
        f'<span style="display: none; max-height: 0; overflow: hidden;">{html.escape(email.preheader)}</span>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" '
        'style="padding: 32px 16px;"><table role="presentation" width="100%" style="max-width: 560px; '
        'background: #ffffff; border-radius: 8px;"><tr><td style="padding: 32px;">'
        f'<h1 style="margin: 0 0 16px; font-size: 22px; line-height: 1.3; color: #111827;">{html.escape(email.heading)}</h1>'
        f"{paragraphs}{button}</td></tr></table>"
        f'<table role="presentation" width="100%" style="max-width: 560px;"><tr><td style="padding: 16px 32px;">{footer}'
        "</td></tr></table></td></tr></table></body></html>"
    )


def _render_text(email: IdeaEmail, url: str) -> str:
    parts = [email.heading, *email.paragraphs]
    if url:
        parts.append(f"{email.button_text}: {url}")
    parts.append("Unsubscribe: {{ unsubscribe_url }}")
    return "\n\n".join(parts)


def _render_design(email: IdeaEmail, url: str, footer: str) -> dict[str, Any]:
    """The same email as blocks for the visual editor, which cannot rebuild blocks from HTML."""
    contents: list[dict[str, Any]] = [
        _block(
            "heading",
            {"headingType": "h1", "fontSize": "22px", "textAlign": "left", "lineHeight": "130%", "color": "#111827"},
            text=f"<strong>{html.escape(email.heading)}</strong>",
        ),
        _block(
            "text",
            {"fontSize": "15px", "textAlign": "left", "lineHeight": "160%", "color": "#374151"},
            text="".join(f'<p style="line-height: 160%;">{html.escape(p)}</p><p>&nbsp;</p>' for p in email.paragraphs),
        ),
    ]
    if url:
        contents.append(
            _block(
                "button",
                {
                    "href": {
                        "name": "web",
                        "attrs": {"href": "{{href}}", "target": "{{target}}"},
                        "values": {"href": url, "target": "_blank"},
                    },
                    "buttonColors": {
                        "color": "#FFFFFF",
                        "backgroundColor": BUTTON_COLOR,
                        "hoverColor": "#FFFFFF",
                        "hoverBackgroundColor": "#374151",
                    },
                    "size": {"autoWidth": True, "width": "100%"},
                    "fontSize": "15px",
                    "lineHeight": "120%",
                    "textAlign": "left",
                    "padding": "12px 22px",
                    "borderRadius": "6px",
                },
                text=f"<strong>{html.escape(email.button_text)}</strong>",
            )
        )
    contents.append({"type": "custom", "slug": "unsubscribe_link", "values": {"unsubscribe_link_content": footer}})
    for position, block in enumerate(contents):
        block["id"] = f"idea_block_{position}"
        block["values"].setdefault("containerPadding", "10px")
    return {
        "counters": {"u_row": 1, "u_column": 1},
        "schemaVersion": 23,
        "body": {
            "id": "idea_body",
            "rows": [
                {
                    "id": "idea_row",
                    "cells": [1],
                    "columns": [{"id": "idea_column", "contents": contents, "values": {}}],
                    "values": {},
                }
            ],
            "values": {
                "contentWidth": "560px",
                "contentAlign": "center",
                "backgroundColor": "#f9fafb",
                "textColor": "#374151",
                "preheaderText": email.preheader,
                "fontFamily": {"label": "Helvetica", "value": "helvetica,sans-serif"},
                "linkStyle": {
                    "body": True,
                    "linkColor": "#111827",
                    "linkHoverColor": "#374151",
                    "linkUnderline": True,
                    "linkHoverUnderline": True,
                },
            },
        },
    }


def _block(kind: str, values: dict[str, Any], *, text: str) -> dict[str, Any]:
    return {"type": kind, "values": {**values, "text": text}}


def find_site_url(team_id: int, app_urls: list[str] | None) -> str | None:
    """The project's own site, for the email buttons: its authorized URLs first, then its busiest pageview host."""
    for url in app_urls or []:
        if url.startswith("https://") and "*" not in url:
            return url.rstrip("/")
    with tags_context(product=Product.WORKFLOWS, feature=Feature.ENRICHMENT):
        response = execute_hogql_query(
            "SELECT properties.$host AS host, count() AS n FROM events WHERE event = '$pageview' "
            "AND timestamp > now() - INTERVAL 30 DAY AND host IS NOT NULL AND host NOT LIKE '%localhost%' "
            "GROUP BY host ORDER BY n DESC LIMIT 1",
            team=Team.objects.get(id=team_id),
        )
    rows = response.results or []
    return f"https://{rows[0][0]}" if rows else None


def people_reached_since(team_id: int, trigger_event: str, goal_events: list[str], since: datetime) -> int | None:
    """People with an email address who hit the trigger after `since` and have not reached a goal: who a live
    version of the draft would have emailed by now."""
    try:
        with tags_context(product=Product.WORKFLOWS, feature=Feature.QUERY):
            response = execute_hogql_query(
                "SELECT count(DISTINCT person_id) FROM events WHERE event = {trigger} AND timestamp > {since} "
                "AND notEmpty(toString(person.properties.email)) AND person_id NOT IN ("
                "SELECT person_id FROM events WHERE event IN {goals} AND timestamp > {since})",
                placeholders={
                    "trigger": ast.Constant(value=trigger_event),
                    "goals": ast.Tuple(exprs=[ast.Constant(value=goal) for goal in goal_events]),
                    "since": ast.Constant(value=since),
                },
                team=Team.objects.get(id=team_id),
            )
    except Exception as error:
        logger.warning("workflow_idea_reach_query_failed", team_id=team_id, error=str(error))
        return None
    rows = response.results or []
    return int(rows[0][0]) if rows else 0
