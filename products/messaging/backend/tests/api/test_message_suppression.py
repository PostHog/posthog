from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic

from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.messaging.backend.models.email_hard_bounce import GLOBAL_HARD_BOUNCE_COPY_DIAGNOSTIC
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource


class TestSuppressionListPersonalAPIKeyAccess(APIBaseTest):
    """
    Guards the token scopes on the read action. It needs both hog_flow:read and person:read, so
    neither alone opens up the recipient addresses and SMTP diagnostics the rows carry. Session auth
    skips scope checks entirely, so only a token exercises this.
    """

    def _key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
        )
        return value

    @parameterized.expand(
        [
            (["hog_flow:read", "person:read"], 200),
            (["hog_flow:read"], 403),
            (["person:read"], 403),
        ]
    )
    def test_suppressions_read_requires_both_scopes(self, scopes: list[str], expected_status: int) -> None:
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/messaging_suppressions/suppressions/",
            HTTP_AUTHORIZATION=f"Bearer {self._key(scopes)}",
        )

        assert response.status_code == expected_status, response.json()
        if expected_status == 200:
            assert set(response.json()) == {"count", "next", "previous", "results"}

    @parameterized.expand(
        [
            ("remove_suppression", {"identifier": "a@example.com"}, ["hog_flow:write", "person:read"], 404),
            ("remove_suppression", {"identifier": "a@example.com"}, ["hog_flow:write"], 403),
            ("bulk_remove_suppressions", {"identifiers": ["a@example.com"]}, ["hog_flow:write", "person:read"], 200),
            ("bulk_remove_suppressions", {"identifiers": ["a@example.com"]}, ["hog_flow:write"], 403),
        ]
    )
    def test_removal_requires_person_read(
        self, action: str, body: dict, scopes: list[str], expected_status: int
    ) -> None:
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_suppressions/{action}/",
            body,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self._key(scopes)}",
        )

        assert response.status_code == expected_status


class TestSuppressionListSearch(APIBaseTest):
    def test_search_filters_by_identifier_within_suppressed_rows(self) -> None:
        for identifier in ["alice@example.com", "bob@example.com"]:
            MessageSuppression.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                identifier=identifier,
                source=SuppressionSource.MANUAL,
                suppressed=True,
            )
        # Bounce-counting row that hasn't crossed the threshold: matches the search term but must
        # stay off the list because it isn't suppressed
        MessageSuppression.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            identifier="alice@not-suppressed.com",
            source=SuppressionSource.BOUNCE,
            suppressed=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/messaging_suppressions/suppressions/", {"search": "ALICE"}
        )

        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["identifier"] == "alice@example.com"

    def test_search_term_too_long(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/messaging_suppressions/suppressions/", {"search": "a" * 513}
        )
        assert response.status_code == 400


class TestRemoveSuppressionResetsSource(APIBaseTest):
    """
    Guards against a regression where remove_suppression keeps source='MANUAL' on the removed row.
    The node upserts preserve suppressed/deleted `WHEN source = 'MANUAL'`, so a manual entry that
    was removed via the API would never be auto-suppressed again — not even by a hard bounce —
    and would stay hidden from the UI (which filters deleted=false).
    """

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/messaging_suppressions/{action}/"

    def test_remove_resets_source_to_bounce_so_future_auto_suppression_can_run(self) -> None:
        # Manual add → row exists as MANUAL, suppressed.
        response = self.client.post(self._url("add_suppression"), {"identifier": "user@example.com"}, format="json")
        assert response.status_code in (200, 201)

        row = MessageSuppression.objects.for_team(self.team.id).get(identifier="user@example.com")
        assert row.source == SuppressionSource.MANUAL
        assert row.suppressed
        MessageSuppression.objects.for_team(self.team.id).filter(pk=row.pk).update(
            hard_bounced_at=timezone.now(), reason="Auto-suppressed after a hard bounce"
        )

        # Remove — the row should be un-suppressed AND its source reset so that the ON CONFLICT
        # branches in the node write path (which skip MANUAL rows) can re-suppress it later.
        response = self.client.post(self._url("remove_suppression"), {"identifier": "user@example.com"}, format="json")
        assert response.status_code == 204

        row.refresh_from_db()
        assert (
            row.suppressed,
            row.deleted,
            row.transient_bounce_count,
            row.hard_bounced_at,
            row.reason,
            row.source,
        ) == (
            False,
            True,
            0,
            None,
            None,
            SuppressionSource.BOUNCE,
        ), (
            "remove_suppression must reset the row so the node write path can auto-suppress this address again if it later bounces"
        )


class TestBulkAddSuppressions(APIBaseTest):
    def _bulk_add(self, suppressions: list[dict[str, str]]):
        return self.client.post(
            f"/api/projects/{self.team.id}/messaging_suppressions/bulk_add_suppressions/",
            {"suppressions": suppressions},
            format="json",
        )

    def test_rejects_more_than_1000_entries(self) -> None:
        response = self._bulk_add([{"identifier": f"user{i}@example.com"} for i in range(1001)])

        assert response.status_code == 400, response.json()
        assert not MessageSuppression.objects.for_team(self.team.id).exists()

    def test_re_adding_is_idempotent(self) -> None:
        suppressions = [
            {"identifier": "alice@example.com", "reason": "bounce"},
            {"identifier": "bob@example.com", "reason": "complaint"},
        ]

        first = self._bulk_add(suppressions)
        second = self._bulk_add(suppressions)

        assert first.status_code == 200, first.json()
        assert first.json() == {"total": 2, "created": 2, "already_present": 0}
        assert second.status_code == 200, second.json()
        assert second.json() == {"total": 2, "created": 0, "already_present": 2}
        assert MessageSuppression.objects.for_team(self.team.id).count() == 2

    def test_identifiers_are_lowercased_and_trimmed(self) -> None:
        response = self._bulk_add(
            [
                {"identifier": "  Alice@Example.COM ", "reason": "bounce"},
                {"identifier": "alice@example.com", "reason": "manual"},
            ]
        )

        assert response.status_code == 200, response.json()
        assert response.json() == {"total": 1, "created": 1, "already_present": 0}
        row = MessageSuppression.objects.for_team(self.team.id).get()
        assert (row.identifier, row.source, row.suppressed, row.hard_bounced_at is not None) == (
            "alice@example.com",
            SuppressionSource.BOUNCE,
            True,
            True,
        )

    @parameterized.expand(
        [
            ("complaint", {"source": SuppressionSource.COMPLAINT, "reason": "Spam complaint"}, "Spam complaint"),
            ("manual", {"source": SuppressionSource.MANUAL, "reason": "Manually added"}, "Manually added"),
            (
                "soft_bounces",
                {"source": SuppressionSource.BOUNCE, "reason": "Soft bounced 3 times"},
                "Imported (bounced)",
            ),
            ("counting_soft_bounces", {"source": SuppressionSource.BOUNCE, "suppressed": False}, "Imported (bounced)"),
            (
                "global_list_copy",
                {
                    "source": SuppressionSource.BOUNCE,
                    "reason": "Hard bounced",
                    "hard_bounced_at": timezone.now(),
                    "last_bounce_diagnostic": GLOBAL_HARD_BOUNCE_COPY_DIAGNOSTIC,
                },
                "Imported (bounced)",
            ),
        ]
    )
    def test_imported_bounce_makes_an_existing_entry_block_transactional_email(
        self, _name: str, existing: dict, expected_reason: str
    ) -> None:
        suppressed = existing.get("suppressed", True)
        MessageSuppression.objects.for_team(self.team.id).create(
            team=self.team,
            identifier="alice@example.com",
            suppressed_at=timezone.now() if suppressed else None,
            **{"suppressed": True, **existing},
        )

        response = self._bulk_add([{"identifier": "alice@example.com", "reason": "bounce"}])

        assert response.status_code == 200, response.json()
        assert response.json() == {"total": 1, "created": 0, "already_present": 1}
        row = MessageSuppression.objects.for_team(self.team.id).get()
        assert (
            row.source,
            row.reason,
            row.suppressed,
            row.suppressed_at is not None,
            row.hard_bounced_at is not None,
            row.last_bounce_diagnostic,
        ) == (existing["source"], expected_reason, True, True, True, None)

    @parameterized.expand(
        [
            ("removed_entry_gets_a_bounce", {"suppressed": False, "deleted": True}, "bounce"),
            ("manual_entry_gets_a_complaint", {"source": SuppressionSource.MANUAL, "suppressed": True}, "complaint"),
            ("complaint_entry_gets_a_manual", {"source": SuppressionSource.COMPLAINT, "suppressed": True}, "manual"),
        ]
    )
    def test_import_leaves_an_entry_that_must_not_block_transactional_email_unchanged(
        self, _name: str, existing: dict, imported_reason: str
    ) -> None:
        before = MessageSuppression.objects.for_team(self.team.id).create(
            team=self.team, identifier="alice@example.com", **existing
        )

        response = self._bulk_add([{"identifier": "alice@example.com", "reason": imported_reason}])

        assert response.status_code == 200, response.json()
        after = MessageSuppression.objects.for_team(self.team.id).get()
        assert (after.source, after.suppressed, after.deleted, after.hard_bounced_at, after.updated_at) == (
            before.source,
            before.suppressed,
            before.deleted,
            None,
            before.updated_at,
        )


class TestBulkAddSuppressionsWithConcurrentBounceWrites(NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_import_lets_a_bounce_write_holding_one_of_its_rows_finish(self):
        rows = MessageSuppression.objects.for_team(self.team.id)
        for identifier in ["a@example.com", "b@example.com"]:
            rows.create(
                team=self.team,
                identifier=identifier,
                source=SuppressionSource.MANUAL,
                reason="Manually added",
                suppressed=True,
                suppressed_at=timezone.now(),
            )
        worker_pid: Queue[int] = Queue()

        def import_bounces():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    worker_pid.put(cursor.fetchone()[0])
                return self.client.post(
                    f"/api/projects/{self.team.id}/messaging_suppressions/bulk_add_suppressions/",
                    {
                        "suppressions": [
                            {"identifier": i, "reason": "bounce"} for i in ["a@example.com", "b@example.com"]
                        ]
                    },
                    format="json",
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                rows.filter(identifier="b@example.com").update(transient_bounce_count=F("transient_bounce_count") + 1)
                response = executor.submit(import_bounces)
                pid = worker_pid.get(timeout=10)
                deadline = monotonic() + 10
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    holder_pid = cursor.fetchone()[0]
                    while not response.done() and monotonic() < deadline:
                        cursor.execute("SELECT %s = ANY(pg_blocking_pids(%s))", [holder_pid, pid])
                        if cursor.fetchone()[0]:
                            break
                    else:
                        self.fail("The import did not wait for the bounce write")
                rows.filter(identifier="a@example.com").update(transient_bounce_count=F("transient_bounce_count") + 1)
            assert response.result(timeout=10).status_code == 200

        assert [
            (row.identifier, row.transient_bounce_count, row.hard_bounced_at is not None)
            for row in rows.order_by("identifier")
        ] == [
            ("a@example.com", 1, True),
            ("b@example.com", 1, True),
        ]


class TestRemoveSuppressions(APIBaseTest):
    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/messaging_suppressions/{action}/"

    def _suppress(self, identifier: str, source: SuppressionSource, team_id: int | None = None) -> None:
        team_id = team_id or self.team.id
        MessageSuppression.objects.for_team(team_id).create(
            team_id=team_id, identifier=identifier, source=source, suppressed=True, suppressed_at=timezone.now()
        )

    def _suppressed(self) -> set[str]:
        return set(
            MessageSuppression.objects.for_team(self.team.id)
            .filter(suppressed=True, deleted=False)
            .values_list("identifier", flat=True)
        )

    @parameterized.expand(
        [
            ("unconfirmed", {}, 400, {"spam@example.com"}),
            ("confirmed", {"confirm_complaints": True}, 204, set()),
        ]
    )
    def test_removing_a_complaint_needs_confirmation(
        self, _name: str, extra: dict, expected_status: int, still_suppressed: set[str]
    ) -> None:
        self._suppress("spam@example.com", SuppressionSource.COMPLAINT)

        response = self.client.post(
            self._url("remove_suppression"), {"identifier": "spam@example.com", **extra}, format="json"
        )

        assert response.status_code == expected_status
        assert self._suppressed() == still_suppressed

    @parameterized.expand(
        [
            (
                "removes what is listed and reports the rest",
                {"identifiers": ["Bounced@Example.com", "manual@example.com", "unknown@example.com"]},
                200,
                {"spam@example.com"},
            ),
            (
                "removes nothing while a complaint is unconfirmed",
                {"identifiers": ["bounced@example.com", "spam@example.com"]},
                400,
                {"bounced@example.com", "manual@example.com", "spam@example.com"},
            ),
            (
                "removes a confirmed complaint",
                {"identifiers": ["bounced@example.com", "spam@example.com"], "confirm_complaints": True},
                200,
                {"manual@example.com"},
            ),
        ]
    )
    def test_bulk_remove(self, _name: str, body: dict, expected_status: int, still_suppressed: set[str]) -> None:
        self._suppress("bounced@example.com", SuppressionSource.BOUNCE)
        self._suppress("manual@example.com", SuppressionSource.MANUAL)
        self._suppress("spam@example.com", SuppressionSource.COMPLAINT)

        response = self.client.post(self._url("bulk_remove_suppressions"), body, format="json")

        assert response.status_code == expected_status
        assert self._suppressed() == still_suppressed

    @parameterized.expand(
        [
            ("with no row", None),
            ("already removed", {"suppressed": False, "deleted": True}),
            ("no longer suppressed", {"suppressed": False}),
        ]
    )
    def test_bulk_remove_reports_removed_and_absent_addresses(self, _name: str, absent_row: dict | None) -> None:
        self._suppress("bounced@example.com", SuppressionSource.BOUNCE)
        absent = MessageSuppression.objects.for_team(self.team.id).filter(identifier="absent@example.com")
        if absent_row is not None:
            self._suppress("absent@example.com", SuppressionSource.BOUNCE)
            absent.update(transient_bounce_count=2, **absent_row)
        absent_before = list(absent.values("suppressed", "deleted", "source", "transient_bounce_count"))

        response = self.client.post(
            self._url("bulk_remove_suppressions"),
            {"identifiers": ["bounced@example.com", "absent@example.com"]},
            format="json",
        )
        single = self.client.post(self._url("remove_suppression"), {"identifier": "absent@example.com"}, format="json")

        assert response.json() == {"removed": ["bounced@example.com"], "not_found": ["absent@example.com"]}
        assert single.status_code == 404
        assert list(absent.values("suppressed", "deleted", "source", "transient_bounce_count")) == absent_before

    def test_another_projects_entry_can_be_neither_listed_nor_removed(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._suppress("shared@example.com", SuppressionSource.BOUNCE, team_id=other_team.id)

        listed = self.client.get(self._url("suppressions"))
        removed = self.client.post(
            self._url("bulk_remove_suppressions"), {"identifiers": ["shared@example.com"]}, format="json"
        )

        assert listed.json()["count"] == 0
        assert removed.json() == {"removed": [], "not_found": ["shared@example.com"]}
        assert MessageSuppression.objects.for_team(other_team.id).get(identifier="shared@example.com").suppressed
