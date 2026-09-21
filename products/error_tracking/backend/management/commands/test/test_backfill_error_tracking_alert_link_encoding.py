from posthog.test.base import BaseTest

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.error_tracking.backend.management.commands.backfill_error_tracking_alert_link_encoding import Command

RAW_LINK = (
    "{project.url}/error_tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}"
    "?timestamp={event.properties.exception_timestamp}&utm_source=alert"
)
ENCODED_LINK = (
    "{project.url}/error_tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}"
    "?timestamp={event.properties.exception_timestamp ? "
    "encodeURLComponent(event.properties.exception_timestamp) : ''}&utm_source=alert"
)


def reloaded_inputs(destination: HogFunction) -> dict:
    destination.refresh_from_db()
    return destination.inputs or {}


class TestBackfillErrorTrackingAlertLinkEncoding(BaseTest):
    def _destination(self, name: str, inputs: dict) -> HogFunction:
        # HogFunction.save() rebuilds inputs from inputs_schema, so every key needs an entry there.
        return HogFunction.objects.create(
            team=self.team,
            name=name,
            type="destination",
            enabled=True,
            inputs=inputs,
            inputs_schema=[{"key": key, "type": "string"} for key in inputs],
            hog="return true",
        )

    def test_encodes_the_timestamp_in_nested_and_flat_inputs_and_recompiles_them(self) -> None:
        # The Slack sub-template buries the link inside a block structure, so a rewrite that only
        # walks bare strings (the shape Linear and GitHub use) would miss it.
        slack = self._destination(
            "slack alert",
            {
                "blocks": {
                    "value": [{"type": "actions", "elements": [{"type": "button", "url": RAW_LINK}]}],
                    "bytecode": ["_H", 1],
                },
                "channel": {"value": "#alerts", "bytecode": ["_H", 1]},
            },
        )
        linear = self._destination("linear alert", {"link": {"value": RAW_LINK, "bytecode": ["_H", 1]}})
        untouched = self._destination("unrelated", {"url": {"value": "{project.url}/home", "bytecode": ["_H", 1]}})

        Command().handle(live_run=True, batch_size=1)

        slack_inputs = reloaded_inputs(slack)
        linear_inputs = reloaded_inputs(linear)
        untouched_inputs = reloaded_inputs(untouched)

        assert slack_inputs["blocks"]["value"][0]["elements"][0]["url"] == ENCODED_LINK
        assert linear_inputs["link"]["value"] == ENCODED_LINK
        assert untouched_inputs["url"]["value"] == "{project.url}/home"

        # A stale bytecode would keep sending the old URL however the stored value reads, and the
        # untouched input must not be recompiled at all.
        assert slack_inputs["blocks"]["bytecode"] != ["_H", 1]
        assert slack_inputs["channel"]["bytecode"] == ["_H", 1]
        assert linear_inputs["link"]["bytecode"] != ["_H", 1]
        assert untouched_inputs["url"]["bytecode"] == ["_H", 1]

    def test_dry_run_leaves_the_destination_alone(self) -> None:
        destination = self._destination("linear alert", {"link": {"value": RAW_LINK, "bytecode": ["_H", 1]}})

        Command().handle(live_run=False, batch_size=1_000)

        inputs = reloaded_inputs(destination)
        assert inputs["link"]["value"] == RAW_LINK
        assert inputs["link"]["bytecode"] == ["_H", 1]
