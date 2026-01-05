import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.logs.backend.has_logs_query_runner import HasLogsQueryRunner


class TestHasLogsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs_schema.sql")) as f:
            schema_sql = f.read()
        for sql in schema_sql.split(";"):
            if not sql.strip():
                continue
            sync_execute(sql)

    def test_has_logs_returns_false_when_no_logs(self):
        runner = HasLogsQueryRunner(self.team)
        self.assertFalse(runner.run())

    def test_has_logs_returns_true_when_logs_exist(self):
        # Insert a log entry
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            line = f.readline()
            log_item = json.loads(line)
            log_item["team_id"] = self.team.id
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {json.dumps(log_item)}
            """)

        runner = HasLogsQueryRunner(self.team)
        self.assertTrue(runner.run())

    def test_has_logs_respects_team_isolation(self):
        # Insert a log entry for a different team
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            line = f.readline()
            log_item = json.loads(line)
            log_item["team_id"] = 99999  # Different team
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {json.dumps(log_item)}
            """)

        # Should return false for our team
        runner = HasLogsQueryRunner(self.team)
        self.assertFalse(runner.run())


class TestHasLogsAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs_schema.sql")) as f:
            schema_sql = f.read()
        for sql in schema_sql.split(";"):
            if not sql.strip():
                continue
            sync_execute(sql)

    def test_has_logs_api_returns_false_when_no_logs(self):
        response = self.client.get(f"/api/projects/{self.team.id}/logs/has_logs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"hasLogs": False})

    def test_has_logs_api_returns_true_when_logs_exist(self):
        # Insert a log entry
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            line = f.readline()
            log_item = json.loads(line)
            log_item["team_id"] = self.team.id
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {json.dumps(log_item)}
            """)

        response = self.client.get(f"/api/projects/{self.team.id}/logs/has_logs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"hasLogs": True})

    def test_has_logs_api_requires_authentication(self):
        self.client.logout()
        response = self.client.get(f"/api/projects/{self.team.id}/logs/has_logs")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
