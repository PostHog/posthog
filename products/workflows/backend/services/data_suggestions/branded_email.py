from html import escape

from posthog.cdp.validation import build_html_wrap_design
from posthog.dataclasses import frozen

from products.workflows.backend.services.data_suggestions.brand import BrandKit

_FALLBACK_ACCENT = "#1d1f27"


@frozen
class EmailCopy:
    subject: str
    heading: str
    paragraphs: tuple[str, ...]
    button_label: str


@frozen
class RenderedEmail:
    subject: str
    html: str
    text: str
    design: dict


def render_branded_email(copy: EmailCopy, brand: BrandKit | None) -> RenderedEmail:
    accent = _usable_accent(brand.primary_color if brand else None)
    button_text_color = "#ffffff" if _luminance(accent) < 0.5 else "#1d1f27"
    # Without a known site there is no safe link target, so the email goes out without a button.
    button_url = f"https://{brand.domain}" if brand else None

    header = ""
    if brand:
        logo = (
            f'<img src="{escape(brand.logo_url)}" alt="" width="40" height="40" '
            f'style="display:block;border-radius:8px;margin-bottom:12px">'
            if brand.logo_url
            else ""
        )
        header = (
            f'<tr><td style="padding:24px 32px;border-bottom:4px solid {accent}">{logo}'
            f'<div style="font-size:16px;font-weight:600;color:#1d1f27">{escape(brand.site_name)}</div></td></tr>'
        )

    button = (
        f'<a href="{escape(button_url)}" style="display:inline-block;margin-top:8px;padding:12px 20px;'
        f"border-radius:6px;background:{accent};color:{button_text_color};font-weight:600;"
        f'text-decoration:none">{escape(copy.button_label)}</a>'
        if button_url
        else ""
    )
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;font-size:16px;line-height:24px;color:#3b3d45">{escape(paragraph)}</p>'
        for paragraph in copy.paragraphs
    )
    html = (
        '<!DOCTYPE html><html><body style="margin:0;padding:24px 0;background:#f5f5f2;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px">'
        f"{header}"
        '<tr><td style="padding:32px">'
        f'<h1 style="margin:0 0 16px;font-size:24px;line-height:32px;color:#1d1f27">{escape(copy.heading)}</h1>'
        f"{paragraphs}"
        f"{button}"
        "</td></tr>"
        '<tr><td style="padding:16px 32px 32px;font-size:12px;color:#6b6e76">'
        '<a href="{{ unsubscribe_url }}" style="color:#6b6e76">Unsubscribe</a></td></tr>'
        "</table></body></html>"
    )
    text_parts = [copy.heading, *copy.paragraphs]
    if button_url:
        text_parts.append(f"{copy.button_label}: {button_url}")
    text = "\n\n".join(text_parts)
    return RenderedEmail(subject=copy.subject, html=html, text=text, design=build_html_wrap_design(html))


def _usable_accent(color: str | None) -> str:
    # A near-white theme color would make the header rule and the button disappear on a white email.
    if not color or _luminance(color) > 0.9:
        return _FALLBACK_ACCENT
    return color


def _luminance(color: str) -> float:
    hex_value = color.lstrip("#")
    if len(hex_value) == 3:
        hex_value = "".join(char * 2 for char in hex_value)
    red, green, blue = (int(hex_value[index : index + 2], 16) / 255 for index in (0, 2, 4))

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
