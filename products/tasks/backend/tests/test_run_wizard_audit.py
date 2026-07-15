import json

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.temporal.process_task.activities.run_wizard_audit import (
    _MAX_DETAILS_CHARS,
    _MAX_LABEL_CHARS,
    _parse_checks,
)


class TestParseAuditChecks(SimpleTestCase):
    @parameterized.expand(
        [
            ("not_a_list", json.dumps({"id": "x"}), []),
            ("non_dict_entries", json.dumps(["x", 1, None]), []),
            ("missing_required_fields", json.dumps([{"id": "a"}, {"label": "b", "status": "pass"}]), []),
            (
                "bookkeeping_rows_dropped",
                json.dumps([{"id": "write-report", "label": "w", "status": "pending"}]),
                [],
            ),
        ]
    )
    def test_rejects_unusable_ledgers(self, _name: str, raw: str, expected: list) -> None:
        self.assertEqual(_parse_checks(raw), expected)

    def test_keeps_valid_checks_and_truncates_details(self) -> None:
        raw = json.dumps(
            [
                {
                    "id": "identify-stable-distinct-id",
                    "area": "identify",
                    # Every ledger field is repository-controlled, so the short fields are capped too.
                    "label": "L" * (_MAX_LABEL_CHARS + 500),
                    "status": "error",
                    "file": "src/auth.ts",
                    "details": "x" * (_MAX_DETAILS_CHARS + 500),
                },
                # Non-string optional fields are nulled, not persisted as garbage.
                {"id": "init-correct", "label": "Init correct", "status": "pass", "area": 3, "file": {}},
            ]
        )

        checks = _parse_checks(raw)

        self.assertEqual(len(checks), 2)
        self.assertEqual(checks[0]["id"], "identify-stable-distinct-id")
        self.assertEqual(len(checks[0]["label"]), _MAX_LABEL_CHARS)
        self.assertEqual(len(checks[0]["details"]), _MAX_DETAILS_CHARS)
        self.assertEqual(
            checks[1],
            {
                "id": "init-correct",
                "area": None,
                "label": "Init correct",
                "status": "pass",
                "file": None,
                "details": None,
            },
        )
