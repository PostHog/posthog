import json
from uuid import UUID

from freezegun.api import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, snapshot_clickhouse_queries
from unittest import mock
from unittest.mock import patch

from django.db import IntegrityError

from flaky import flaky
from orjson import orjson
from rest_framework import status

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.helpers.dashboard_templates import create_group_type_mapping_detail_dashboard
from posthog.models import GroupTypeMapping, GroupUsageMetric, Person
from posthog.models.group.util import create_group
from posthog.models.organization import Organization
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team.team import Team
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.notebooks.backend.models import Notebook, ResourceNotebook

PATH = "ee.clickhouse.views.groups"


class GroupsViewSetTestCase(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    @freeze_time("2021-05-02")
    def test_groups_list(self):
        with freeze_time("2021-05-01"):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:5",
                properties={"industry": "finance", "name": "Mr. Krabs"},
            )
        with freeze_time("2021-05-02"):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:6",
                properties={"industry": "technology"},
            )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"name": "Plankton"},
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-02T00:00:00Z",
                        "group_key": "org:6",
                        "group_properties": {"industry": "technology"},
                        "group_type_index": 0,
                    },
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )
        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&search=Krabs").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&search=org:5").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )

    @freeze_time("2021-05-02")
    def test_groups_list_no_group_type(self):
        response_data = self.client.get(f"/api/projects/{self.team.id}/groups/").json()
        self.assertEqual(
            response_data,
            {
                "type": "validation_error",
                "attr": "group_type_index",
                "code": "invalid_input",
                "detail": mock.ANY,
            },
        )

    def test_retrieve_group_wrong_group_type_index(self):
        group = create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="key",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/find?group_type_index=1&group_key={group.group_key}"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, "Should return 404 Not Found")

    def test_retrieve_group_wrong_group_key(self):
        group = create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="key",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/find?group_type_index={group.group_type_index}&group_key=wrong_key"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, "Should return 404 Not Found")

    @freeze_time("2021-05-02")
    @patch(f"{PATH}.posthoganalytics.feature_enabled", return_value=False)
    def test_retrieve_group_crm_disabled(self, _):
        index = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": key,
                "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                "group_type_index": index,
                "notebook": None,
            },
        )
        self.assertFalse(ResourceNotebook.objects.filter(group=group.id).exists())
        self.assertEqual(0, Notebook.objects.filter(team=self.team).count())

    @freeze_time("2021-05-02")
    @patch(f"{PATH}.posthoganalytics.feature_enabled", return_value=True)
    def test_retrieve_group_crm_enabled(self, _):
        index = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        relationships = ResourceNotebook.objects.filter(group=group.id)
        self.assertIsNotNone(relationships)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": key,
                "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                "group_type_index": index,
                "notebook": relationships.first().notebook.short_id,
            },
        )
        self.assertEqual(1, Notebook.objects.filter(team=self.team).count())

        # Test default notebook content structure
        notebook = relationships.first().notebook
        self.assertIsNotNone(notebook.content)
        self.assertEqual(notebook.content[0]["type"], "heading")
        self.assertEqual(notebook.content[0]["attrs"]["level"], 1)
        self.assertEqual(notebook.content[0]["content"][0]["text"], "Mr. Krabs Notes")
        self.assertEqual(notebook.content[1]["type"], "text")

    @freeze_time("2021-05-02")
    def test_retrieve_group_with_notebook(self):
        index = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )
        notebook = Notebook.objects.create(team=self.team, title="Mr. Krabs Notes")
        ResourceNotebook.objects.create(group=group.id, notebook=notebook)

        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": key,
                "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                "group_type_index": index,
                "notebook": notebook.short_id,
            },
        )

    @freeze_time("2021-05-02")
    @patch(f"{PATH}.ResourceNotebook.objects.create", side_effect=IntegrityError)
    @patch(f"{PATH}.posthoganalytics.feature_enabled", return_value=True)
    def test_retrieve_group_notebook_transaction_rollback(self, _, mock_relationship_create):
        index = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        initial_notebook_count = Notebook.objects.filter(team=self.team).count()
        self.assertEqual(initial_notebook_count, 0)

        with self.assertLogs(level="ERROR") as logs:
            response = self.client.get(
                f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        final_notebook_count = Notebook.objects.filter(team=self.team).count()
        self.assertEqual(final_notebook_count, initial_notebook_count, "Notebook creation should be rolled back")
        self.assertFalse(ResourceNotebook.objects.filter(group=group.id).exists())
        mock_relationship_create.assert_called_once()
        self.assertEqual(len(logs.records), 1)
        log = logs.records[0]
        self.assertEqual(log.msg["group_key"], key)
        self.assertEqual(log.msg["group_type_index"], index)
        self.assertEqual(log.msg["team_id"], self.team.pk)
        self.assertEqual(log.msg["event"], "Group notebook creation failed")

    @freeze_time("2021-05-02")
    @mock.patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    def test_create_group_missing_group_properties(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group_key = "1234"

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": group_key,
                "group_type_index": group_type_mapping.group_type_index,
                "group_properties": None,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": group_key,
                "group_properties": {},
                "group_type_index": group_type_mapping.group_type_index,
            },
        )
        mock_capture.assert_called_once()

    @freeze_time("2021-05-02")
    @mock.patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    @flaky(max_runs=3, min_passes=1)
    def test_create_group(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group_properties = {"name": "Group Name", "industry": "finance"}
        group_key = "1234"

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": group_key,
                "group_type_index": group_type_mapping.group_type_index,
                "group_properties": group_properties,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": group_key,
                "group_properties": group_properties,
                "group_type_index": 0,
            },
        )
        response = execute_hogql_query(
            parse_select(
                """
                select properties
                from groups
                where index = {index}
                  and key = {key}
                """,
                placeholders={
                    "index": ast.Constant(value=group_type_mapping.group_type_index),
                    "key": ast.Constant(value=group_key),
                },
            ),
            self.team,
        )
        self.assertEqual(response.results, [(json.dumps(group_properties),)])
        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$groupidentify",
            event_source="ee_ch_views_groups",
            distinct_id=str(self.team.uuid),
            timestamp=mock.ANY,
            properties={
                "$group_type": group_type_mapping.group_type,
                "$group_key": group_key,
                "$group_set": group_properties,
            },
            process_person_profile=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key={group_key}&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result["activity"], "create_group")
            self.assertEqual(result["scope"], "Group")
            self.assertEqual(result["detail"]["changes"][0]["action"], "created")
            self.assertIsNone(result["detail"]["changes"][0]["before"])
            prop_name = result["detail"]["name"]
            self.assertEqual(result["detail"]["changes"][0]["after"], group_properties[prop_name])

    @mock.patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    def test_create_group_duplicated_group_key(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group_key = "1234"
        create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key=group_key,
            properties={},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": group_key,
                "group_type_index": 0,
                "group_properties": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "A group with this key already exists",
                "attr": "detail",
            },
        )
        mock_capture.assert_not_called()

    @mock.patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    def test_create_group_missing_group_key(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": None,
                "group_type_index": group_type_mapping.group_type_index,
                "group_properties": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "group_key",
                "code": "null",
                "detail": "This field may not be null.",
                "type": "validation_error",
            },
        )
        mock_capture.assert_not_called()

    @mock.patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    def test_create_group_missing_group_type_index(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": "foo",
                "group_type_index": None,
                "group_properties": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "group_type_index",
                "code": "null",
                "detail": "This field may not be null.",
                "type": "validation_error",
            },
        )
        mock_capture.assert_not_called()

    @freeze_time("2021-05-02")
    @mock.patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    @flaky(max_runs=3, min_passes=1)
    def test_group_property_crud_add_success(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group = create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"name": "Mr. Krabs"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:55",
            properties={"name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "org:5",
                "group_properties": {"industry": "technology", "name": "Mr. Krabs"},
                "group_type_index": 0,
            },
        )

        response = execute_hogql_query(
            parse_select(
                """
                select properties
                from groups
                where index = {index}
                and key = {key}
                """,
                placeholders={
                    "index": ast.Constant(value=group.group_type_index),
                    "key": ast.Constant(value=group.group_key),
                },
            ),
            self.team,
        )
        self.assertEqual(response.results, [('{"name": "Mr. Krabs", "industry": "technology"}',)])

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$groupidentify",
            event_source="ee_ch_views_groups",
            distinct_id=str(self.team.uuid),
            timestamp=mock.ANY,
            properties={
                "$group_type": group_type_mapping.group_type,
                "$group_key": group.group_key,
                "$group_set": {"industry": "technology"},
            },
            process_person_profile=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["activity"], "update_property")
        self.assertEqual(response.json()["results"][0]["scope"], "Group")
        self.assertEqual(response.json()["results"][0]["item_id"], str(group.pk))
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["type"], "Group")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["action"], "created")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["before"], None)
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["after"], "technology")

    @freeze_time("2021-05-02")
    @mock.patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    @flaky(max_runs=3, min_passes=1)
    def test_group_property_crud_update_success(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group = create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "org:5",
                "group_properties": {"industry": "technology", "name": "Mr. Krabs"},
                "group_type_index": 0,
            },
        )

        response = execute_hogql_query(
            parse_select(
                """
                select properties
                from groups
                where index = {index}
                and key = {key}
                """,
                placeholders={
                    "index": ast.Constant(value=group.group_type_index),
                    "key": ast.Constant(value=group.group_key),
                },
            ),
            self.team,
        )
        # Check properties regardless of JSON key order
        self.assertEqual(len(response.results), 1)
        self.assertEqual(len(response.results[0]), 1)
        self.assertEqual(orjson.loads(response.results[0][0]), {"name": "Mr. Krabs", "industry": "technology"})

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$groupidentify",
            event_source="ee_ch_views_groups",
            distinct_id=str(self.team.uuid),
            timestamp=mock.ANY,
            properties={
                "$group_type": group_type_mapping.group_type,
                "$group_key": group.group_key,
                "$group_set": {"industry": "technology"},
            },
            process_person_profile=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["activity"], "update_property")
        self.assertEqual(response.json()["results"][0]["scope"], "Group")
        self.assertEqual(response.json()["results"][0]["item_id"], str(group.pk))
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["type"], "Group")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["action"], "changed")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["before"], "finance")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["after"], "technology")

    @freeze_time("2021-05-02")
    def test_group_property_crud_update_missing_key(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"value": "technology"},
        )
        self.assertEqual(response.status_code, 400)

    @freeze_time("2021-05-02")
    def test_group_property_crud_update_invalid_group_key(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:0&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )
        self.assertEqual(response.status_code, 404)

    @freeze_time("2021-05-02")
    @mock.patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    @flaky(max_runs=3, min_passes=1)
    def test_group_property_crud_delete_success(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group = create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:5&group_type_index=0",
            {"$unset": "industry"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "org:5",
                "group_properties": {"name": "Mr. Krabs"},
                "group_type_index": 0,
            },
        )

        response = execute_hogql_query(
            parse_select(
                """
                select properties
                from groups
                where index = {index}
                and key = {key}
                """,
                placeholders={
                    "index": ast.Constant(value=group.group_type_index),
                    "key": ast.Constant(value=group.group_key),
                },
            ),
            self.team,
        )
        self.assertEqual(response.results, [('{"name": "Mr. Krabs"}',)])

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$delete_group_property",
            event_source="ee_ch_views_groups",
            distinct_id=str(self.team.uuid),
            timestamp=mock.ANY,
            properties={
                "$group_type": group_type_mapping.group_type,
                "$group_key": group.group_key,
                "$group_unset": ["industry"],
            },
            process_person_profile=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["activity"], "update_property")
        self.assertEqual(response.json()["results"][0]["scope"], "Group")
        self.assertEqual(response.json()["results"][0]["item_id"], str(group.pk))
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["type"], "Group")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["action"], "deleted")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["before"], "finance")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["after"], None)

    @freeze_time("2021-05-02")
    def test_group_property_crud_delete_missing_key(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:5&group_type_index=0",
            {},
        )
        self.assertEqual(response.status_code, 400)

    @freeze_time("2021-05-02")
    def test_group_property_crud_delete_invalid_group_key(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:0&group_type_index=0",
            {"$unset": "industry"},
        )
        self.assertEqual(response.status_code, 404)

    @freeze_time("2021-05-02")
    @patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    def test_get_group_activities_success(self, mock_capture):
        # Mock the response to return a 200 OK
        mock_capture.return_value = mock.MagicMock(status_code=200)

        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group = create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        # Triggers the entry
        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )

        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["activity"], "update_property")
        self.assertEqual(response.json()["results"][0]["scope"], "Group")
        self.assertEqual(response.json()["results"][0]["item_id"], str(group.pk))
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["type"], "Group")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["action"], "changed")

    @freeze_time("2021-05-02")
    @patch("products.enterprise.backend.clickhouse.views.groups.capture_internal")
    def test_get_group_activities_invalid_group(self, mock_capture):
        # Mock the response to return a 200 OK
        mock_capture.return_value = mock.MagicMock(status_code=200)

        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=group_type_mapping.group_type_index,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        # Triggers the entry
        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )

        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=1",
        )

        self.assertEqual(response.status_code, 404)

    @freeze_time("2021-05-10")
    @snapshot_clickhouse_queries
    def test_related_groups(self):
        self._create_related_groups_data()

        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/related?id=0::0&group_type_index=0"
        ).json()
        self.assertEqual(
            response_data,
            [
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "distinct_ids": ["1", "2"],
                    "id": "01795392-cc00-0003-7dc7-67a694604d72",
                    "uuid": "01795392-cc00-0003-7dc7-67a694604d72",
                    "is_identified": False,
                    "name": "1",
                    "properties": {},
                    "type": "person",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::2",
                    "group_type_index": 1,
                    "id": "1::2",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::3",
                    "group_type_index": 1,
                    "id": "1::3",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
            ],
        )

    @freeze_time("2021-05-10")
    @snapshot_clickhouse_queries
    def test_related_groups_person(self):
        uuid = self._create_related_groups_data()

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups/related?id={uuid}").json()
        self.assertEqual(
            response_data,
            [
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "0::0",
                    "group_type_index": 0,
                    "id": "0::0",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "0::1",
                    "group_type_index": 0,
                    "id": "0::1",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::2",
                    "group_type_index": 1,
                    "id": "1::2",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::3",
                    "group_type_index": 1,
                    "id": "1::3",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
            ],
        )

    def test_property_definitions(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"name": "Plankton"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:2",
            properties={},
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups/property_definitions").json()
        self.assertEqual(
            response_data,
            {
                "0": [{"name": "industry", "count": 2}, {"name": "name", "count": 1}],
                "1": [{"name": "name", "count": 1}],
            },
        )

    def test_property_values(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:7",
            properties={"industry": "finance-technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"industry": "finance"},
        )

        # Test without query parameter
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0"
        ).json()
        self.assertEqual(len(response_data), 3)
        self.assertEqual(
            response_data,
            [
                {"name": "finance", "count": 1},
                {"name": "finance-technology", "count": 1},
                {"name": "technology", "count": 1},
            ],
        )

        # Test with query parameter
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0&value=fin"
        ).json()
        self.assertEqual(len(response_data), 2)
        self.assertEqual(response_data, [{"name": "finance", "count": 1}, {"name": "finance-technology", "count": 1}])

        # Test with query parameter - case insensitive
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0&value=TECH"
        ).json()
        self.assertEqual(len(response_data), 2)
        self.assertEqual(
            response_data, [{"name": "finance-technology", "count": 1}, {"name": "technology", "count": 1}]
        )

        # Test with query parameter - no matches
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0&value=healthcare"
        ).json()
        self.assertEqual(len(response_data), 0)
        self.assertEqual(response_data, [])

        # Test with query parameter - exact match
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0&value=technology"
        ).json()
        self.assertEqual(len(response_data), 2)
        self.assertEqual(
            response_data, [{"name": "finance-technology", "count": 1}, {"name": "technology", "count": 1}]
        )

        # Test with different group_type_index
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=1&value=fin"
        ).json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data, [{"name": "finance", "count": 1}])

    def test_empty_property_values(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"industry": "finance"},
        )
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=name&group_type_index=0"
        ).json()
        self.assertEqual(len(response_data), 0)
        self.assertEqual(response_data, [])

    def test_update_groups_metadata(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="another", group_type_index=2
        )

        response_data = self.client.patch(
            f"/api/projects/{self.team.id}/groups_types/update_metadata",
            [
                {"group_type_index": 0, "name_singular": "organization!"},
                {
                    "group_type_index": 1,
                    "group_type": "rename attempt",
                    "name_plural": "playlists",
                },
            ],
        ).json()

        self.assertEqual(
            response_data,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": "organization!",
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": "playlists",
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
            ],
        )

    def test_list_group_types(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="another", group_type_index=2
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups_types").json()

        self.assertEqual(
            response_data,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
            ],
        )

    def test_cannot_list_group_types_of_another_org(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")

        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="another", group_type_index=2
        )

        response = self.client.get(f"/api/projects/{other_team.id}/groups_types")  # No access to this project

        self.assertEqual(response.status_code, 403, response.json())
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You don't have access to the project."),
        )

    def test_cannot_list_group_types_of_another_org_with_sharing_token(self):
        sharing_configuration = SharingConfiguration.objects.create(team=self.team, enabled=True)

        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")

        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="another", group_type_index=2
        )

        response = self.client.get(
            f"/api/projects/{other_team.id}/groups_types/?sharing_access_token={sharing_configuration.access_token}"
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You do not have permission to perform this action."),
        )

    def test_can_list_group_types_of_another_org_with_sharing_access_token(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")
        sharing_configuration = SharingConfiguration.objects.create(team=other_team, enabled=True)

        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="another", group_type_index=2
        )

        disabled_response = self.client.get(
            f"/api/projects/{other_team.id}/groups_types/?sharing_access_token={sharing_configuration.access_token}"
        ).json()

        self.assertEqual(
            disabled_response,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
            ],
        )

        # Disable the config now
        sharing_configuration.enabled = False
        sharing_configuration.save()

        disabled_response = self.client.get(
            f"/api/projects/{other_team.id}/groups_types?sharing_access_token={sharing_configuration.access_token}"
        )

        self.assertEqual(disabled_response.status_code, 403, disabled_response.json())
        self.assertEqual(
            disabled_response.json(),
            self.unauthenticated_response("Sharing access token is invalid.", "authentication_failed"),
        )

    def test_create_detail_dashboard_success(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/create_detail_dashboard",
            {"group_type_index": 0},
        )
        self.assertEqual(response.status_code, 200)

        group_type_mapping.refresh_from_db()
        self.assertIsNotNone(group_type_mapping.detail_dashboard)

    def test_create_detail_dashboard_duplicate(self):
        group_type = create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        dashboard = create_group_type_mapping_detail_dashboard(group_type, self.user)
        group_type.detail_dashboard = dashboard
        group_type.save()

        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/create_detail_dashboard",
            {"group_type_index": 0},
        )
        self.assertEqual(response.status_code, 400)

    def test_create_detail_dashboard_not_found(self):
        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/create_detail_dashboard",
            {"group_type_index": 1},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Group type not found")

    def test_set_default_columns_success(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/set_default_columns",
            {"group_type_index": 0, "default_columns": ["$group_0", "$group_1"]},
        )
        self.assertEqual(response.status_code, 200)

        group_type_mapping.refresh_from_db()
        self.assertEqual(group_type_mapping.default_columns, ["$group_0", "$group_1"])

    def test_set_default_columns_not_found(self):
        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/set_default_columns",
            {"group_type_index": 1, "default_columns": ["$group_0", "$group_1"]},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Group type not found")

    def _create_related_groups_data(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="playlist", group_type_index=1
        )

        uuid = UUID("01795392-cc00-0003-7dc7-67a694604d72")

        Person.objects.create(uuid=uuid, team_id=self.team.pk, distinct_ids=["1", "2"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["3"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["4"])

        create_group(self.team.pk, 0, "0::0")
        create_group(self.team.pk, 0, "0::1")
        create_group(self.team.pk, 1, "1::2")
        create_group(self.team.pk, 1, "1::3")
        create_group(self.team.pk, 1, "1::4")
        create_group(self.team.pk, 1, "1::5")

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::2"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::3"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::1", "$group_1": "1::3"},
        )

        # Event too old, not counted
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2000-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::4"},
        )

        # No such group exists in groups table
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2000-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "no such group"},
        )

        return uuid


class GroupsTypesViewSetTestCase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/groups_types"

    def test_delete(self):
        group_type_data = {
            "team": self.team,
            "project": self.project,
            "group_type": "organization",
            "group_type_index": 0,
        }
        group_type = create_group_type_mapping_without_created_at(**group_type_data)
        delete_url = self.url + f"/{group_type.group_type_index}"

        delete_response = self.client.delete(delete_url)

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GroupTypeMapping.objects.filter(**group_type_data).exists())

        list_response = self.client.get(self.url)

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.json()), 0)

    def test_create_detail_dashboard(self):
        GroupTypeMapping.objects.create(
            team=self.team, project=self.project, group_type="organization", group_type_index=0
        )

        response = self.client.put(self.url + "/create_detail_dashboard", {"group_type_index": 0})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["group_type"], "organization")
        self.assertEqual(data["group_type_index"], 0)
        self.assertIsNotNone(data["detail_dashboard"])


class GroupUsageMetricViewSetTestCase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.group_type = GroupTypeMapping.objects.create(
            team=self.team, project=self.project, group_type="organization", group_type_index=0
        )
        self.url = f"/api/projects/{self.team.id}/groups_types/{str(self.group_type.group_type_index)}/metrics"

        self.other_org = Organization.objects.create(name="other org")
        self.other_team = Team.objects.create(organization=self.other_org, name="other team")
        self.other_group_type = GroupTypeMapping.objects.create(
            team=self.other_team, project_id=self.other_team.project_id, group_type="company", group_type_index=0
        )
        self.other_url = (
            f"/api/projects/{self.other_team.id}/groups_types/{str(self.other_group_type.group_type_index)}/metrics"
        )

    def assertFields(self, data, metric):
        self.assertEqual(data["id"], str(metric.id))
        self.assertEqual(data["name"], metric.name)
        self.assertEqual(data["format"], metric.format)
        self.assertEqual(data["interval"], metric.interval)
        self.assertEqual(data["display"], metric.display)
        self.assertEqual(data["filters"], metric.filters)

    def _create_metric(self, **kwargs):
        defaults = {
            "team": self.team,
            "group_type_index": self.group_type.group_type_index,
            "name": "Events",
            "filters": {"foo": "bar"},
        }
        defaults.update(kwargs)
        return GroupUsageMetric.objects.create(**defaults)

    def test_list(self):
        metric = self._create_metric()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFields(response.json()["results"][0], metric)

    def test_create(self):
        payload = {"name": "Events", "filters": {"foo": "bar"}}

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        metric = GroupUsageMetric.objects.get(id=response.json().get("id"))
        self.assertFields(response.json(), metric)
        self.assertEqual(metric.team, self.team, "Should set team automatically")
        self.assertEqual(
            metric.group_type_index, self.group_type.group_type_index, "Should set group_type_index automatically"
        )
        self.assertIsNotNone(metric.bytecode, "Should set bytecode automatically")

    def test_retrieve(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFields(response.json(), metric)

    def test_update(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        payload = {
            "name": "Updated Events",
            "format": "currency",
            "interval": 30,
            "display": "sparkline",
            "filters": {"updated": "value"},
        }

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Updated Events")
        self.assertEqual(metric.format, "currency")
        self.assertEqual(metric.interval, 30)
        self.assertEqual(metric.display, "sparkline")
        self.assertEqual(metric.filters, {"updated": "value"})
        self.assertFields(response.json(), metric)

    def test_delete(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GroupUsageMetric.objects.filter(id=metric.id).exists())

    def test_partial_update(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        payload = {"name": "Partially Updated Events"}

        response = self.client.patch(url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Partially Updated Events")
        self.assertEqual(metric.format, "numeric", "Should remain unchanged")
        self.assertEqual(metric.interval, 7, "Should remain unchanged")
        self.assertEqual(metric.display, "number", "Should remain unchanged")

    def test_delete_nonexistent(self):
        fake_id = "00000000-0000-0000-0000-000000000000"
        url = f"{self.url}/{fake_id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_nonexistent(self):
        fake_id = "00000000-0000-0000-0000-000000000000"
        url = f"{self.url}/{fake_id}"
        payload = {"name": "Updated Events"}

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_access(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthorized_team_access(self):
        self._create_metric(group_type_index=self.other_group_type.group_type_index, team=self.other_team)

        response = self.client.get(self.other_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_access(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_creation(self):
        payload = {"name": "Unauthorized Events"}

        response = self.client.post(self.other_url, payload)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_modification(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"
        payload = {"name": "Hacked Events"}

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_deletion(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

        self.assertTrue(GroupUsageMetric.objects.filter(id=other_metric.id).exists())
