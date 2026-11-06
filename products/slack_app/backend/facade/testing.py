"""Test-support facade for slack_app.

Sibling products' tests build a Slack ``Integration`` fixture standing for a workspace whose bot
can answer a mention, which means writing the granted scope string the bot actually requires.

``facade.api`` does not carry the scope set, because no production caller outside slack_app needs
it: ``slack_followup_invite_text`` resolves readiness itself and returns the setup link when the
install falls short. Exposing it here keeps that production surface closed while the fixtures that
genuinely need the value still have one supported way to read it.
"""

from products.slack_app.backend.services.slack_scopes import REQUIRED_SLACK_SCOPES

__all__ = ["REQUIRED_SLACK_SCOPES"]
