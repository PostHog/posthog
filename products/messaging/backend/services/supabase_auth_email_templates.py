"""Starter templates for the Supabase auth emails, written against the variables the Send Email Hook passes."""

from typing import Any

from posthog.dataclasses import frozen

from products.messaging.backend.facade.contracts import SupabaseEmailActionType


@frozen
class StarterTemplate:
    name: str
    subject: str
    preheader: str
    heading: str
    body: str
    # Without a button the email shows the one-time code instead.
    button_label: str | None


STARTER_TEMPLATES: dict[SupabaseEmailActionType, StarterTemplate] = {
    SupabaseEmailActionType.SIGNUP: StarterTemplate(
        name="Supabase: confirm sign up",
        subject="Confirm your email address",
        preheader="Confirm your email address to finish signing up.",
        heading="Confirm your email address",
        body="Confirm your email address to finish signing up.",
        button_label="Confirm email address",
    ),
    SupabaseEmailActionType.INVITE: StarterTemplate(
        name="Supabase: invite user",
        subject="You have been invited",
        preheader="Accept the invite to create your account.",
        heading="You have been invited",
        body="You have been invited to create an account. Accept the invite to set it up.",
        button_label="Accept invite",
    ),
    SupabaseEmailActionType.MAGICLINK: StarterTemplate(
        name="Supabase: magic link",
        subject="Your sign-in link",
        preheader="Use this link to sign in.",
        heading="Sign in",
        body="Use the button below to sign in. If you didn't ask for this link, you can ignore this email.",
        button_label="Sign in",
    ),
    SupabaseEmailActionType.RECOVERY: StarterTemplate(
        name="Supabase: reset password",
        subject="Reset your password",
        preheader="Use this link to choose a new password.",
        heading="Reset your password",
        body="Use the button below to choose a new password. If you didn't ask to reset it, you can ignore this email.",
        button_label="Reset password",
    ),
    SupabaseEmailActionType.EMAIL_CHANGE: StarterTemplate(
        name="Supabase: change email address",
        subject="Confirm your new email address",
        preheader="Confirm the change to your email address.",
        heading="Confirm your email address change",
        body="Confirm that you want to change your email address from {{ variables.email }} to {{ variables.new_email }}.",
        button_label="Confirm change",
    ),
    SupabaseEmailActionType.REAUTHENTICATION: StarterTemplate(
        name="Supabase: reauthentication",
        subject="Your verification code",
        preheader="Enter this code to confirm it's you.",
        heading="Confirm it's you",
        body="Enter this code to continue. If you didn't ask for it, you can ignore this email.",
        button_label=None,
    ),
}

STARTER_EMAIL_TYPES = frozenset(STARTER_TEMPLATES)


def _html(template: StarterTemplate) -> str:
    if template.button_label:
        action = (
            '<p style="margin:24px 0">'
            '<a href="{{ variables.confirmation_url }}" style="background:#1d4aff;border-radius:6px;color:#ffffff;'
            f'display:inline-block;font-weight:600;padding:12px 20px;text-decoration:none">{template.button_label}</a>'
            "</p>"
            '<p style="color:#6b7280;font-size:13px">Or enter this code: <strong>{{ variables.token }}</strong></p>'
        )
    else:
        action = '<p style="font-size:28px;font-weight:600;letter-spacing:4px;margin:24px 0">{{ variables.token }}</p>'
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;'
        'color:#111827;line-height:1.5;max-width:480px;margin:0 auto;padding:24px">'
        f'<h1 style="font-size:20px;margin:0 0 16px">{template.heading}</h1>'
        f"<p>{template.body}</p>"
        f"{action}"
        "</div>"
    )


def _block(block_id: str, block_type: str, number: int, values: dict[str, Any]) -> dict[str, Any]:
    html_class = f"u_content_{block_type}"
    return {
        "id": block_id,
        "type": block_type,
        "values": {
            "textAlign": "left",
            **values,
            "_meta": {"htmlID": f"{html_class}_{number}", "htmlClassNames": html_class},
        },
    }


def _paragraph(block_id: str, number: int, text: str, **values: str) -> dict[str, Any]:
    return _block(
        block_id,
        "text",
        number,
        {"text": f"<p>{text}</p>", "fontSize": "16px", "lineHeight": "150%", "containerPadding": "8px 24px", **values},
    )


def _design(template: StarterTemplate) -> dict[str, Any]:
    """The same email as `_html`, built from native Unlayer blocks so each part opens as its own editable block.
    Ids are fixed, so every starter set gets the same design."""
    contents = [
        _block(
            "heading",
            "heading",
            1,
            {
                "headingType": "h1",
                "text": template.heading,
                "fontSize": "22px",
                "fontWeight": 600,
                "lineHeight": "130%",
                "containerPadding": "32px 24px 8px",
            },
        ),
        _paragraph("text-body", 1, template.body),
    ]
    if template.button_label:
        contents += [
            _block(
                "button-confirm",
                "button",
                1,
                {
                    "text": template.button_label,
                    "href": {"name": "web", "values": {"href": "{{ variables.confirmation_url }}", "target": "_blank"}},
                    "buttonColors": {
                        "color": "#ffffff",
                        "backgroundColor": "#1d4aff",
                        "hoverColor": "#ffffff",
                        "hoverBackgroundColor": "#1d4aff",
                    },
                    "fontSize": "16px",
                    "padding": "12px 20px",
                    "borderRadius": "6px",
                    "containerPadding": "16px 24px",
                },
            ),
            _paragraph(
                "text-code",
                2,
                "Or enter this code: <strong>{{ variables.token }}</strong>",
                fontSize="13px",
                color="#6b7280",
            ),
        ]
    else:
        contents.append(
            _paragraph(
                "text-code",
                2,
                "<strong>{{ variables.token }}</strong>",
                fontSize="28px",
                lineHeight="130%",
                containerPadding="16px 24px 32px",
            )
        )

    counters = {"u_row": 1, "u_column": 1}
    for content in contents:
        key = f"u_content_{content['type']}"
        counters[key] = counters.get(key, 0) + 1
    return {
        "counters": counters,
        "schemaVersion": 16,
        "body": {
            "id": "supabase-auth-email",
            "headers": [],
            "footers": [],
            "values": {
                "backgroundColor": "#ffffff",
                "contentWidth": "480px",
                "textColor": "#111827",
                "fontFamily": {"label": "Helvetica", "value": "helvetica,arial,sans-serif"},
            },
            "rows": [
                {
                    "id": "row-main",
                    "cells": [1],
                    "values": {"padding": "0px", "_meta": {"htmlID": "u_row_1", "htmlClassNames": "u_row"}},
                    "columns": [
                        {
                            "id": "column-main",
                            "values": {"_meta": {"htmlID": "u_column_1", "htmlClassNames": "u_column"}},
                            "contents": contents,
                        }
                    ],
                }
            ],
        },
    }


def _text(template: StarterTemplate) -> str:
    if template.button_label:
        action = f"{template.button_label}: {{{{ variables.confirmation_url }}}}\n\nOr enter this code: {{{{ variables.token }}}}"
    else:
        action = "Your code: {{ variables.token }}"
    return f"{template.heading}\n\n{template.body}\n\n{action}\n"


def starter_template_content(template: StarterTemplate) -> dict:
    return {
        "email": {
            "subject": template.subject,
            "preheader": template.preheader,
            "html": _html(template),
            "text": _text(template),
            "design": _design(template),
        }
    }
