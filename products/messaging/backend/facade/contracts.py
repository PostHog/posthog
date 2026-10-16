from dataclasses import dataclass
from typing import Any
from uuid import UUID


class UnlayerError(Exception):
    pass


class UnlayerNotConfiguredError(UnlayerError):
    pass


class UnlayerRenderError(UnlayerError):
    pass


@dataclass(frozen=True)
class EmailTemplateSummary:
    id: UUID
    name: str
    subject: str


@dataclass(frozen=True)
class EmailTemplateContent:
    id: UUID
    name: str
    # The template's email body: subject, html, text and the editor design.
    email: dict[str, Any]


class TransactionalEmailError(Exception):
    """A send the caller has to fix before retrying. `code` is stable for API clients."""

    code = "invalid"


class TemplateNotSendable(TransactionalEmailError):
    code = "template_not_sendable"


class MarketingTemplate(TransactionalEmailError):
    code = "marketing_template"


class SenderUnavailable(TransactionalEmailError):
    code = "sender_unavailable"
