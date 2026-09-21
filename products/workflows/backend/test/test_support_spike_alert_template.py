from django.test import SimpleTestCase

from products.workflows.backend.templates import get_global_template_by_id

SUPPORT_SPIKE_ALERT_ID = "019d4a7c-3b21-0000-9f04-6e2b8c15d730"
# The topic and the summary are written by a model from customer ticket text, so a customer
# can put `<!channel>` or a labelled link in them.
UNTRUSTED_PLACEHOLDERS = ("{event.properties.topic}", "{event.properties.summary}")


class TestSupportSpikeAlertTemplate(SimpleTestCase):
    def _slack_inputs(self) -> dict:
        template = get_global_template_by_id(SUPPORT_SPIKE_ALERT_ID)
        assert template is not None
        slack_action = next(action for action in template["actions"] if action["type"] == "function")
        return slack_action["config"]["inputs"]

    def test_customer_written_spike_text_reaches_only_plain_text_fields(self):
        inputs = self._slack_inputs()
        blocks = inputs["blocks"]["value"]
        as_markup = [b["text"]["text"] for b in blocks if b.get("text", {}).get("type") == "mrkdwn"]
        # Slack reads a message's top-level text as markup too, whatever the blocks say.
        as_markup.append(inputs["text"]["value"])
        as_plain_text = [b["text"]["text"] for b in blocks if b.get("text", {}).get("type") == "plain_text"]

        for placeholder in UNTRUSTED_PLACEHOLDERS:
            assert not any(placeholder in text for text in as_markup)
            assert any(placeholder in text for text in as_plain_text)
