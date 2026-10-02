from html import escape
from typing import Any

from posthog.dataclasses import frozen

from products.workflows.backend.models.email_brand import EmailBrand

STARTER_TEMPLATE_DESCRIPTION = "Created from your Email brand."

WHITE = "#ffffff"
BLACK = "#000000"
FOOTER_TEXT_COLOR = "#6b6b6b"
OUTER_BACKGROUND_COLOR = "#f5f5f5"
LOGO_MAX_WIDTH = "160px"

# Unlayer only shows a design font as selected when label, value and url match one of its defaults exactly.
# https://docs.unlayer.com/builder/font-management/default-fonts
UNLAYER_DEFAULT_FONTS: dict[str, dict[str, str]] = {
    font["label"].lower(): font
    for font in (
        {"label": "Andale Mono", "value": "andale mono,times"},
        {"label": "Arial", "value": "arial,helvetica,sans-serif"},
        {"label": "Arial Black", "value": "arial black,avant garde,arial"},
        {"label": "Book Antiqua", "value": "book antiqua,palatino"},
        {"label": "Comic Sans MS", "value": "comic sans ms,sans-serif"},
        {"label": "Courier New", "value": "courier new,courier"},
        {"label": "Georgia", "value": "georgia,palatino"},
        {"label": "Helvetica", "value": "helvetica,sans-serif"},
        {"label": "Impact", "value": "impact,chicago"},
        {"label": "Tahoma", "value": "tahoma,arial,helvetica,sans-serif"},
        {"label": "Terminal", "value": "terminal,monaco"},
        {"label": "Times New Roman", "value": "times new roman,times"},
        {"label": "Trebuchet MS", "value": "trebuchet ms,geneva"},
        {"label": "Verdana", "value": "verdana,geneva"},
        *(
            {
                "label": label,
                "value": f"'{label}',{generic}",
                "url": f"https://fonts.googleapis.com/css?family={label.replace(' ', '+')}{weights}",
            }
            for label, generic, weights in (
                ("Lobster Two", "cursive", ":400,700"),
                ("Playfair Display", "serif", ":400,700"),
                ("Rubik", "sans-serif", ":400,700"),
                ("Source Sans Pro", "sans-serif", ":400,700"),
                ("Open Sans", "sans-serif", ":400,700"),
                ("Crimson Text", "serif", ":400,700"),
                ("Montserrat", "sans-serif", ":400,700"),
                ("Old Standard TT", "serif", ":400,700"),
                ("Lato", "sans-serif", ":400,700"),
                ("Raleway", "sans-serif", ":400,700"),
                ("Cabin", "sans-serif", ":400,700"),
                ("Pacifico", "cursive", ""),
            )
        ),
    )
}

EDITABLE_BLOCK = {
    "selectable": True,
    "draggable": True,
    "duplicatable": True,
    "deletable": True,
    "hideable": True,
}


@frozen
class StarterTemplate:
    name: str
    subject: str
    design: dict[str, Any]


def build_starter_template(brand: EmailBrand) -> StarterTemplate:
    return StarterTemplate(
        name=f"{brand.name} starter template" if brand.name else "Starter template",
        subject=f"Hello from {brand.name}" if brand.name else "Hello",
        design=build_starter_design(brand),
    )


def build_starter_design(brand: EmailBrand) -> dict[str, Any]:
    header = _header_contents(brand)
    return {
        "counters": _counters(header),
        "schemaVersion": 16,
        "body": {
            "id": "brand-starter-body",
            "headers": [],
            "footers": [],
            "rows": [
                _row("header", brand, header, column_border=_accent_band(brand)),
                _row("content", brand, [_heading(brand), _body_text(brand), _call_to_action(brand)]),
                _row("footer", brand, [_unsubscribe_footer(brand)]),
            ],
            "values": {
                "backgroundColor": OUTER_BACKGROUND_COLOR,
                "contentWidth": "600px",
                "contentAlign": "center",
                "fontFamily": _font(brand),
                "textColor": brand.text_color,
                "linkStyle": _link_style(brand, inherit_key="body"),
                "preheaderText": "",
                "_meta": {"htmlID": "u_body", "htmlClassNames": "u_body"},
            },
        },
    }


def cta_text_color(background: str) -> str:
    return WHITE if _contrast(WHITE, background) >= _contrast(BLACK, background) else BLACK


def _header_contents(brand: EmailBrand) -> list[dict[str, Any]]:
    if brand.logo:
        return [_logo(brand)]
    if brand.name:
        return [_brand_name_heading(brand)]
    return []


def _counters(header: list[dict[str, Any]]) -> dict[str, int]:
    header_types = [content["type"] for content in header]
    return {
        "u_row": 3,
        "u_column": 3,
        "u_content_image": header_types.count("image"),
        "u_content_heading": 1 + header_types.count("heading"),
        "u_content_text": 1,
        "u_content_button": 1,
        "u_content_custom_unsubscribe_link": 1,
    }


def _row(
    name: str, brand: EmailBrand, contents: list[dict[str, Any]], column_border: dict[str, str] | None = None
) -> dict[str, Any]:
    index = ("header", "content", "footer").index(name) + 1
    return {
        "id": f"brand-starter-{name}-row",
        "cells": [1],
        "columns": [
            {
                "id": f"brand-starter-{name}-column",
                "contents": contents,
                "values": {
                    "_meta": {"htmlID": f"u_column_{index}", "htmlClassNames": "u_column"},
                    "border": column_border or {},
                    "padding": "0px",
                    "backgroundColor": "",
                },
            }
        ],
        "values": {
            "displayCondition": None,
            "columns": False,
            "backgroundColor": brand.background_color,
            "columnsBackgroundColor": "",
            "backgroundImage": {"url": "", "fullWidth": True, "repeat": False, "center": True, "cover": False},
            "padding": "0px",
            "_meta": {"htmlID": f"u_row_{index}", "htmlClassNames": "u_row"},
        },
    }


def _accent_band(brand: EmailBrand) -> dict[str, str]:
    return {"borderTopWidth": "4px", "borderTopStyle": "solid", "borderTopColor": brand.accent_color}


def _logo(brand: EmailBrand) -> dict[str, Any]:
    return _content(
        "brand-starter-logo",
        "image",
        "u_content_image_1",
        {
            "containerPadding": "32px 24px 16px",
            "src": {"url": brand.logo.get_absolute_url(), "autoWidth": False, "maxWidth": LOGO_MAX_WIDTH},
            "textAlign": "center",
            "altText": brand.name,
            "action": {"name": "web", "values": {"href": "", "target": "_blank"}},
        },
    )


def _brand_name_heading(brand: EmailBrand) -> dict[str, Any]:
    return _content(
        "brand-starter-name",
        "heading",
        "u_content_heading_2",
        {
            "containerPadding": "32px 24px 16px",
            "headingType": "h2",
            "fontSize": "24px",
            "color": brand.text_color,
            "textAlign": "center",
            "lineHeight": "120%",
            "linkStyle": _link_style(brand),
            "text": escape(brand.name),
        },
    )


def _heading(brand: EmailBrand) -> dict[str, Any]:
    return _content(
        "brand-starter-heading",
        "heading",
        "u_content_heading_1",
        {
            "containerPadding": "8px 24px",
            "headingType": "h1",
            "fontSize": "28px",
            "color": brand.text_color,
            "textAlign": "left",
            "lineHeight": "120%",
            "linkStyle": _link_style(brand),
            "text": "Hi {{ person.properties.first_name | default: 'there' }}",
        },
    )


def _body_text(brand: EmailBrand) -> dict[str, Any]:
    return _content(
        "brand-starter-body-text",
        "text",
        "u_content_text_1",
        {
            "containerPadding": "8px 24px 16px",
            "fontSize": "16px",
            "color": brand.text_color,
            "textAlign": "left",
            "lineHeight": "150%",
            "linkStyle": _link_style(brand),
            "text": "<p>Write your message here. Keep it short and lead with what the reader gets.</p>",
        },
    )


def _call_to_action(brand: EmailBrand) -> dict[str, Any]:
    text_color = cta_text_color(brand.primary_color)
    return _content(
        "brand-starter-cta",
        "button",
        "u_content_button_1",
        {
            "containerPadding": "8px 24px 32px",
            "href": {"name": "web", "values": {"href": "https://example.com", "target": "_blank"}},
            "buttonColors": {
                "color": text_color,
                "backgroundColor": brand.primary_color,
                "hoverColor": text_color,
                "hoverBackgroundColor": brand.primary_color,
            },
            "size": {"autoWidth": True, "width": "100%"},
            "fontSize": "16px",
            "textAlign": "left",
            "lineHeight": "120%",
            "padding": "12px 24px",
            "border": {},
            "borderRadius": "6px",
            "text": "<span>Get started</span>",
        },
    )


def _unsubscribe_footer(brand: EmailBrand) -> dict[str, Any]:
    link_style = f"color: {FOOTER_TEXT_COLOR}; text-decoration: underline;"
    unsubscribe_link = f'<a href="{{{{ unsubscribe_url }}}}" style="{link_style}">Unsubscribe</a>'
    reason = f"You get this email because you use {escape(brand.name)}." if brand.name else ""
    footer = _content(
        "brand-starter-unsubscribe",
        "custom",
        "u_content_custom_unsubscribe_link_1",
        {
            "containerPadding": "16px 24px 32px",
            "unsubscribe_link_content": (
                f'<p style="text-align: center; font-size: 12px; color: {FOOTER_TEXT_COLOR};">'
                f"{' '.join(filter(None, (reason, unsubscribe_link)))}</p>"
            ),
        },
    )
    return {**footer, "slug": "unsubscribe_link"}


def _content(content_id: str, content_type: str, html_id: str, values: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": content_id,
        "type": content_type,
        "values": {
            "anchor": "",
            "hideDesktop": False,
            "displayCondition": None,
            "_meta": {"htmlID": html_id, "htmlClassNames": html_id.rsplit("_", 1)[0]},
            **EDITABLE_BLOCK,
            **values,
        },
    }


def _link_style(brand: EmailBrand, inherit_key: str = "inherit") -> dict[str, Any]:
    return {
        inherit_key: True,
        "linkColor": brand.primary_color,
        "linkHoverColor": brand.primary_color,
        "linkUnderline": True,
        "linkHoverUnderline": True,
    }


def _font(brand: EmailBrand) -> dict[str, str]:
    default = UNLAYER_DEFAULT_FONTS.get(brand.font_family.strip().lower())
    if default is not None:
        return dict(default)
    return {"label": brand.font_family, "value": brand.font_stack}


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(hex_color: str) -> float:
    red, green, blue = (_linear(int(hex_color[index : index + 2], 16) / 255) for index in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
