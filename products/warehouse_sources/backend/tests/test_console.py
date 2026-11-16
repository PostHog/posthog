import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.utils import timezone

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

REENABLE_URL = "/admin/console/tools/warehouse-sources-reenable/"
SCHEMA_TOOL_URL = "/admin/console/tools/warehouse-sources/"
TIMEOUT_ERROR = "OperationalError: connection to server at 10.0.0.1, port 5432 failed: timeout expired"
# `update_should_sync` imports these from the facade when it runs, so patching the facade reaches it.
_TEMPORAL = "products.data_warehouse.backend.facade.api"
# Stands for a new stop time, which the test sets after the preview.
STOPPED_AGAIN = "stopped_again"
STOPPED_AT = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


class TestReenableAutoDisabledSchemasTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )

    def _schema(
        self, name: str, *, stopped_hours_ago: float | None = 1, latest_error: str = TIMEOUT_ERROR, **kwargs
    ) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source=self.source,
            name=name,
            should_sync=False,
            latest_error=latest_error,
            auto_disabled_at=timezone.now() - timedelta(hours=stopped_hours_ago)
            if stopped_hours_ago is not None
            else None,
            sync_type_config={"failure_streak": {"runs": 4}},
            **kwargs,
        )

    def _preview(self, query: str = "days=7", **data: str):
        return self.client.post(f"{REENABLE_URL}reenable/?{query}", {"days": "7", "reason": "Fixed upstream", **data})

    def _confirm(self, preview, query: str = "days=7"):
        return self.client.post(
            f"{REENABLE_URL}reenable/?{query}", {"confirm_token": preview.context["confirm_token"]}, follow=True
        )

    @staticmethod
    def _syncing(*schemas: ExternalDataSchema) -> list[bool]:
        return [ExternalDataSchema.objects.get(id=schema.id).should_sync for schema in schemas]

    def test_page_reads_the_link_contract_filters(self) -> None:
        self._schema("public.orders")
        self._schema("public.users", stopped_hours_ago=None)

        response = self.client.get(f"{REENABLE_URL}?days=3&source_type=Postgres&error=TIMEOUT&team={self.team.pk}")

        content = response.content.decode()
        assert response.status_code == 200
        assert "public.orders" in content
        assert "public.users" not in content
        # The group links to the same tool, narrowed to its source type and error start.
        assert "error=OperationalError%3A+connection+to+server+at" in content
        assert f"{SCHEMA_TOOL_URL}?schema=" in content

    def test_page_shows_only_the_largest_error_groups(self) -> None:
        for name, table in (("public.orders", "orders"), ("public.orders_copy", "orders"), ("public.users", "users")):
            self._schema(name, latest_error=f'relation "public.{table}" does not exist')

        with patch("products.warehouse_sources.backend.console.MAX_GROUPS_SHOWN", 1):
            response = self.client.get(f"{REENABLE_URL}?days=7")

        content = response.content.decode()
        assert "The table shows the 1 largest of 2 groups." in content
        assert "error=relation+%22public.orders%22+does+not+exist" in content
        assert "error=relation+%22public.users%22" not in content

    @parameterized.expand([("days_not_offered", "days=5"), ("team_not_a_number", "team=abc")])
    def test_page_refuses_invalid_filters(self, _name: str, query: str) -> None:
        self._schema("public.orders")

        response = self.client.get(f"{REENABLE_URL}?{query}")

        assert response.status_code == 200
        assert "Fix the filters to see the matching schemas." in response.content.decode()
        assert "public.orders" not in response.content.decode()

    def test_operation_form_is_prefilled_from_the_link(self) -> None:
        response = self.client.get(f"{REENABLE_URL}reenable/?days=14&source_type=Stripe&error=rate+limit")

        form = response.context["form"]
        assert (form["days"].value(), form["source_type"].value(), form["error"].value()) == (
            "14",
            "Stripe",
            "rate limit",
        )

    @patch(f"{_TEMPORAL}.unpause_external_data_schedule")
    @patch(f"{_TEMPORAL}.external_data_workflow_exists", return_value=True)
    def test_reenables_only_previewed_auto_disabled_schemas(self, _exists, _unpause) -> None:
        stopped = self._schema("public.orders")
        user_disabled = self._schema("public.users", stopped_hours_ago=None)
        deleted = self._schema("public.events", deleted=True)
        old = self._schema("public.accounts", stopped_hours_ago=24 * 10)

        preview = self._preview()

        assert preview.status_code == 200
        content = preview.content.decode()
        assert "public.orders" in content
        assert not any(name in content for name in ("public.users", "public.events", "public.accounts"))
        assert self._syncing(stopped) == [False]

        with self.captureOnCommitCallbacks(execute=True):
            result = self._confirm(preview)

        assert "Re-enabled" in result.content.decode()
        assert self._syncing(stopped, user_disabled, deleted, old) == [True, False, False, False]
        stopped.refresh_from_db()
        assert stopped.auto_disabled_at is None
        assert "failure_streak" not in stopped.sync_type_config
        # Each save leaves an audit row for the staff member, so a run cut off by a timeout stays recorded.
        logged = ActivityLog.objects.filter(scope="ExternalDataSchema", item_id=str(stopped.id), activity="updated")
        assert [log.user_id for log in logged] == [self.user.id]

    def test_preview_with_no_match_shows_the_form_again(self) -> None:
        self._schema("public.users", stopped_hours_ago=None)

        response = self._preview()

        assert response.status_code == 400
        assert "No auto-disabled schemas match these filters." in response.content.decode()

    @parameterized.expand(
        [
            ("turned_on", {"should_sync": True, "auto_disabled_at": None}),
            ("stopped_again", {"auto_disabled_at": STOPPED_AGAIN}),
            ("deleted", {"deleted": True}),
            ("turned_off_by_the_user", {"auto_disabled_at": None}),
        ]
    )
    @patch(f"{_TEMPORAL}.unpause_external_data_schedule")
    @patch(f"{_TEMPORAL}.external_data_workflow_exists", return_value=True)
    def test_schema_changed_after_preview_is_skipped(self, _name: str, change: dict, _exists, unpause) -> None:
        changed = self._schema("public.orders")
        unchanged = self._schema("public.users")
        preview = self._preview()
        if change.get("auto_disabled_at") == STOPPED_AGAIN:
            assert changed.auto_disabled_at is not None
            change = {"auto_disabled_at": changed.auto_disabled_at + timedelta(minutes=1)}
        ExternalDataSchema.objects.filter(id=changed.id).update(**change)

        result = self._confirm(preview)

        assert unpause.call_count == 1
        assert unpause.call_args.args == (str(unchanged.id),)
        assert "Skipped schemas were turned on, deleted or stopped again" in result.content.decode()
        assert self._syncing(unchanged) == [True]
        if "should_sync" not in change:
            assert self._syncing(changed) == [False]

    @patch(f"{_TEMPORAL}.unpause_external_data_schedule")
    @patch(f"{_TEMPORAL}.external_data_workflow_exists", return_value=True)
    def test_one_run_takes_the_newest_up_to_the_cap(self, _exists, _unpause) -> None:
        schemas = [self._schema(f"public.table_{hours}", stopped_hours_ago=hours) for hours in (1, 2, 3)]

        with (
            patch("products.warehouse_sources.backend.logic.auto_disabled_schemas.MAX_REENABLE_PER_RUN", 2),
            patch("products.warehouse_sources.backend.console.MAX_REENABLE_PER_RUN", 2),
        ):
            preview = self._preview()
            result = self._confirm(preview)

        assert "Run it again for the rest (1 left)." in preview.content.decode()
        assert self._syncing(*schemas) == [True, True, False]
        assert "Schemas that still match these filters: 1." in result.content.decode()

    @patch(f"{_TEMPORAL}.unpause_external_data_schedule")
    @patch(f"{_TEMPORAL}.external_data_workflow_exists", return_value=True)
    def test_failure_is_reported_and_the_rest_still_run(self, _exists, unpause) -> None:
        first = self._schema("public.orders", stopped_hours_ago=1)
        second = self._schema("public.users", stopped_hours_ago=2)
        unpause.side_effect = [Exception("temporal down"), None]
        preview = self._preview()

        result = self._confirm(preview)

        content = result.content.decode()
        assert result.status_code == 200
        assert "Failed schemas" in content
        assert f"{SCHEMA_TOOL_URL}?schema={first.id}" in content
        # The failed re-enable rolls back, so the schema does not stay on with its schedule paused.
        assert self._syncing(first, second) == [False, True]
        assert unpause.call_count == 2

    @patch(f"{_TEMPORAL}.unpause_external_data_schedule")
    @patch(f"{_TEMPORAL}.external_data_workflow_exists", return_value=True)
    def test_run_stops_starting_schemas_at_the_time_budget(self, _exists, unpause) -> None:
        first = self._schema("public.orders", stopped_hours_ago=1)
        second = self._schema("public.users", stopped_hours_ago=2)
        preview = self._preview()
        clock = {"now": 0.0}

        def slow_unpause(schema_id: str) -> None:
            clock["now"] += 10_000

        unpause.side_effect = slow_unpause
        with patch(
            "products.warehouse_sources.backend.logic.auto_disabled_schemas.monotonic", side_effect=lambda: clock["now"]
        ):
            result = self._confirm(preview)

        content = result.content.decode()
        assert "Not attempted" in content
        assert "reached its 180 second limit" in content
        assert self._syncing(first, second) == [True, False]
        assert unpause.call_count == 1


class TestReenableSyncingOnSchemaPage(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _schema(self, **kwargs) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name="public.users", **kwargs)

    @parameterized.expand(
        [
            # The schema page has no time window, so any stop time offers the operation.
            ("auto_disabled", {"should_sync": False, "auto_disabled_at": STOPPED_AT}, True),
            ("turned_off_by_the_user", {"should_sync": False}, False),
            ("syncing", {"should_sync": True}, False),
            ("deleted", {"should_sync": False, "auto_disabled_at": STOPPED_AT, "deleted": True}, False),
        ]
    )
    @patch(f"{_TEMPORAL}.unpause_external_data_schedule")
    @patch(f"{_TEMPORAL}.external_data_workflow_exists", return_value=True)
    def test_reenable_syncing_is_offered_only_for_auto_disabled(
        self, _name: str, state: dict, offered: bool, _exists, unpause
    ) -> None:
        schema = self._schema(**state)

        page = self.client.get(f"{SCHEMA_TOOL_URL}?schema={schema.id}")
        response = self.client.post(f"{SCHEMA_TOOL_URL}reenable-syncing/?schema={schema.id}")

        assert ("Re-enable syncing" in page.content.decode()) is offered
        schema.refresh_from_db()
        if offered:
            assert response.status_code == 302
            assert schema.should_sync is True
            assert schema.auto_disabled_at is None
            unpause.assert_called_once_with(str(schema.id))
            assert "Syncing is on again. The schedule is unpaused." in [
                str(message) for message in get_messages(response.wsgi_request)
            ]
        else:
            assert response.status_code == 404
            assert schema.should_sync is state["should_sync"]
            unpause.assert_not_called()
