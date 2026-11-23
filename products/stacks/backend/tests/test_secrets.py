from __future__ import annotations

from rest_framework import status

from products.stacks.backend.models import StackDiff, StackSecret
from products.stacks.backend.tests.base import StackAPITestBase, resource

SOURCE = resource("source", "billing", password={"$secret": "DB_PASSWORD"})


class TestSecrets(StackAPITestBase):
    def test_a_secret_reaches_the_engine_only_for_the_names_the_description_uses(self) -> None:
        set_response = self.call("put", "web/secrets/DB_PASSWORD/", {"value": "s3cret-value"})
        self.call("put", "web/secrets/UNUSED/", {"value": "other-value"})

        diff = self.ready_diff([SOURCE])

        assert set_response.status_code == status.HTTP_200_OK
        assert "s3cret-value" not in set_response.content.decode()
        assert diff["status"] == "ready"
        assert self.engine.credentials[-1].secrets == {"DB_PASSWORD": "s3cret-value"}
        assert "s3cret-value" not in repr(self.engine.credentials[-1])
        assert b"s3cret-value" not in bytes(StackSecret.all_teams.get(name="DB_PASSWORD").encrypted_value)
        listed = self.client.get(self.url("web/secrets/")).json()
        assert [secret["name"] for secret in listed["results"]] == ["DB_PASSWORD", "UNUSED"]
        assert "value" not in listed["results"][0]

    def test_a_missing_secret_fails_the_diff_before_the_engine_runs(self) -> None:
        self.call("put", "web/secrets/DB_PASSWORD/", {"value": "s3cret-value"})
        assert self.call("delete", "web/secrets/DB_PASSWORD/").status_code == status.HTTP_204_NO_CONTENT

        diff = self.start_diff([SOURCE]).json()

        assert diff["status"] == "failed"
        assert diff["diff"]["errors"][0]["code"] == "secret_missing"
        assert "DB_PASSWORD" in diff["diff"]["errors"][0]["message"]
        assert self.dispatcher.diffs == []

    def test_a_secret_value_in_an_engine_message_is_stored_redacted(self) -> None:
        self.call("put", "web/secrets/DB_PASSWORD/", {"value": "s3cret-value"})
        self.engine.diff_errors = [{"code": "connection_failed", "message": "Login s3cret-value was refused."}]

        diff = self.ready_diff([SOURCE])

        assert "s3cret-value" not in str(StackDiff.all_teams.get(id=diff["id"]).diff)
        assert diff["diff"]["errors"][0]["message"] == "[redacted]"
