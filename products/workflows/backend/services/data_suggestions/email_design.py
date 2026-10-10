from html import escape

from posthog.cdp.validation import build_html_wrap_design
from posthog.dataclasses import frozen


@frozen
class EmailCopy:
    subject: str
    heading: str
    paragraphs: tuple[str, ...]


@frozen
class RenderedEmail:
    subject: str
    html: str
    text: str
    design: dict


def render_email(copy: EmailCopy) -> RenderedEmail:
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;font-size:16px;line-height:24px;color:#3b3d45">{escape(paragraph)}</p>'
        for paragraph in copy.paragraphs
    )
    html = (
        '<!DOCTYPE html><html><body style="margin:0;padding:24px 0;background:#f5f5f2;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px">'
        '<tr><td style="padding:32px">'
        f'<h1 style="margin:0 0 16px;font-size:24px;line-height:32px;color:#1d1f27">{escape(copy.heading)}</h1>'
        f"{paragraphs}"
        "</td></tr>"
        '<tr><td style="padding:16px 32px 32px;font-size:12px;color:#6b6e76">'
        '<a href="{{ unsubscribe_url }}" style="color:#6b6e76">Unsubscribe</a></td></tr>'
        "</table></body></html>"
    )
    text = "\n\n".join([copy.heading, *copy.paragraphs])
    return RenderedEmail(subject=copy.subject, html=html, text=text, design=build_html_wrap_design(html))
