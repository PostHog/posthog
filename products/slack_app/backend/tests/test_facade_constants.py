from products.slack_app.backend.facade.constants import PUBLIC_CHANNEL_CONVERSATION_TYPES
from products.slack_app.backend.models import SlackThreadTaskMapping


def test_public_channel_conversation_types_are_conversation_types() -> None:
    assert PUBLIC_CHANNEL_CONVERSATION_TYPES == {SlackThreadTaskMapping.ConversationType.PUBLIC_CHANNEL}
