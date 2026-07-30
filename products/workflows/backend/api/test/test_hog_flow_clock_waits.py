from posthog.test.base import APIBaseTest

from parameterized import parameterized

TRIGGER = {
    "id": "trigger_node",
    "name": "trigger",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}


def wait_on(hogql: str) -> dict:
    return {
        "id": "wait_1",
        "name": "wait_1",
        "type": "wait_until_condition",
        "config": {
            "condition": {"filters": {"properties": [{"key": hogql, "type": "hogql", "value": None}]}},
            "max_wait_duration": "20d",
        },
    }


class TestClockBasedWaitRejection(APIBaseTest):
    def _post(self, wait: dict) -> tuple[int, dict]:
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "Test Flow", "status": "active", "actions": [TRIGGER, wait]},
        )
        return response.status_code, response.json()

    @parameterized.expand(
        [
            ("now_comparison", "now() >= toDateTime(person.properties.expires_at)"),
            ("unix_wrapped", "toUnixTimestamp(now()) >= toUnixTimestamp(person.properties.expires_at)"),
            ("date_diff", "dateDiff('day', toDateTime(person.properties.last_seen_at), now()) >= 14"),
            ("today", "today() >= toDate(person.properties.expires_at)"),
            # Nested inside arithmetic rather than compared directly, so a top-level-only check misses it.
            ("nested_in_arithmetic", "person.properties.count > toUnixTimestamp(now()) - 86400"),
            # Combined with a stream-observable predicate: one clock term is enough to make the whole
            # condition unwakeable, so an AND must not launder it past the gate.
            (
                "anded_with_a_person_property",
                "person.properties.plan == 'pro' and now() >= toDateTime(person.properties.expires_at)",
            ),
        ]
    )
    def test_rejects_a_wait_that_depends_on_the_clock(self, _name: str, hogql: str):
        # Nothing notifies the matcher when time passes, so these can only advance on a re-check.
        # Each shape has to be caught wherever the clock call sits, not just at the top level.
        status, body = self._post(wait_on(hogql))

        assert status == 400, body
        assert "depends on the current time" in str(body)

    @parameterized.expand(
        [
            ("person_property", "person.properties.plan == 'enterprise'"),
            ("event_name", "event == 'subscription created'"),
            ("property_with_a_date_value", "toDateTime(person.properties.expires_at) > toDateTime('2026-01-01')"),
        ]
    )
    def test_accepts_a_wait_a_stream_can_wake(self, _name: str, hogql: str):
        # The complement, and the part worth guarding: a date comparison is fine as long as both sides
        # are fixed. Rejecting those too would block ordinary conditions and push people off the feature.
        status, body = self._post(wait_on(hogql))

        assert status == 201, body

    def test_accepts_an_events_only_wait(self):
        # No condition to inspect: the wait is woken by its own events entry.
        wait = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "events": [
                    {"filters": {"events": [{"id": "purchase", "name": "purchase", "type": "events", "order": 0}]}}
                ],
                "max_wait_duration": "1h",
            },
        }

        status, body = self._post(wait)

        assert status == 201, body

    def test_a_draft_from_the_builder_can_still_be_saved(self):
        # Drafts from the web builder stay lenient so a half-built graph saves. The gate applies when
        # the flow is activated, which is the point at which the wait would actually run.
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {
                "name": "Test Flow",
                "status": "draft",
                "actions": [TRIGGER, wait_on("now() >= toDateTime(person.properties.expires_at)")],
            },
        )

        assert response.status_code == 201, response.json()
