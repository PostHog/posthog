import re
from html import escape

from posthog.dataclasses import frozen

from products.cdp.backend.validation import build_html_wrap_design


@frozen
class EmailCopy:
    subject: str
    heading: str
    paragraphs: tuple[str, ...]
    # The trigger event's properties the copy may show, written as [[name|fallback]].
    variables: frozenset[str] = frozenset()


@frozen
class RenderedEmail:
    subject: str
    html: str
    text: str
    design: dict


_VARIABLE = re.compile(r"\[\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|([^\[\]|]*))?\]\]")


def with_variables(text: str, variables: frozenset[str]) -> str:
    """Turns [[name|fallback]] into a Liquid variable on the trigger event. An unknown name keeps only its fallback,
    so the model can never reach person data or other events."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        fallback = re.sub(r"['{}%]", "", match.group(2) or "").strip()
        if name not in variables:
            return fallback
        return f"{{{{ event.properties.{name} | default: '{fallback}' }}}}"

    return _VARIABLE.sub(replace, text).replace("[[", "").replace("]]", "")


def render_email(copy: EmailCopy) -> RenderedEmail:
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;font-size:16px;line-height:24px;color:#3b3d45">'
        f"{with_variables(escape(paragraph), copy.variables)}</p>"
        for paragraph in copy.paragraphs
    )
    html = (
        '<!DOCTYPE html><html><body style="margin:0;padding:24px 0;background:#f5f5f2;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px">'
        '<tr><td style="padding:32px">'
        f'<h1 style="margin:0 0 16px;font-size:24px;line-height:32px;color:#1d1f27">'
        f"{with_variables(escape(copy.heading), copy.variables)}</h1>"
        f"{paragraphs}"
        "</td></tr>"
        '<tr><td style="padding:16px 32px 32px;font-size:12px;color:#6b6e76">'
        '<a href="{{ unsubscribe_url }}" style="color:#6b6e76">Unsubscribe</a></td></tr>'
        "</table></body></html>"
    )
    text = with_variables("\n\n".join([copy.heading, *copy.paragraphs]), copy.variables)
    subject = with_variables(copy.subject, copy.variables)
    return RenderedEmail(subject=subject, html=html, text=text, design=build_html_wrap_design(html))
