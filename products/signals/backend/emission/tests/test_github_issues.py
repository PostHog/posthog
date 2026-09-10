import pytest
from unittest.mock import patch

from products.signals.backend.contracts import GithubIssueSignalExtra
from products.signals.backend.emission import (
    github_issues as github_issues_module,
    pipeline,
)
from products.signals.backend.emission.github_issues import EXTRA_FIELDS, GITHUB_ISSUES_CONFIG, github_issue_emitter
from products.signals.backend.emission.pipeline import build_emitter_outputs


class TestGithubIssueEmitter:
    def test_emits_signal_for_valid_issue(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.source_product == "github"
        assert result.source_type == "issue"
        assert result.source_id == "12345"
        assert result.weight == 1.0
        assert "Charts fail to render" in result.description
        assert "special characters" in result.description

    def test_includes_body_in_description(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert "blank white area" in result.description

    @pytest.mark.parametrize("body", [None, ""])
    def test_skips_issue_with_no_body(self, github_issue_record, body):
        github_issue_record["body"] = body
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is None

    @pytest.mark.parametrize("missing_field", ["id", "title"])
    def test_raises_when_required_field_falsy(self, github_issue_record, missing_field):
        github_issue_record[missing_field] = None
        with pytest.raises(ValueError, match="empty required field"):
            github_issue_emitter(team_id=1, record=github_issue_record)

    @pytest.mark.parametrize("missing_field", ["id", "title"])
    def test_raises_when_required_field_empty(self, github_issue_record, missing_field):
        github_issue_record[missing_field] = ""
        with pytest.raises(ValueError, match="empty required field"):
            github_issue_emitter(team_id=1, record=github_issue_record)

    def test_raises_for_empty_record(self):
        with pytest.raises(ValueError, match="missing required field"):
            github_issue_emitter(team_id=1, record={})

    def test_extra_contains_only_expected_fields(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert set(result.extra.keys()) <= set(EXTRA_FIELDS)
        assert "body" not in result.extra
        assert "title" not in result.extra

    def test_extra_preserves_field_values(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.extra["html_url"] == "https://github.com/acme/analytics/issues/87"
        assert result.extra["number"] == 87

    def test_author_lifted_out_of_nested_user_object(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.extra["author_login"] == "octocat"
        assert result.extra["author_association"] == "CONTRIBUTOR"
        # The rest of the user object is avatar and API URLs; only the handle belongs in `extra`.
        assert "user" not in result.extra

    def test_author_satisfies_extra_contract(self, github_issue_record):
        # The eval fixtures predate the author columns, so this is the only coverage of a populated
        # author against a contract that forbids unknown keys.
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        GithubIssueSignalExtra(**result.extra)

    @pytest.mark.parametrize(
        "record_overrides",
        [
            pytest.param({}, id="columns_absent"),
            pytest.param({"user": None, "author_association": None}, id="null_columns"),
            pytest.param({"user": "not-json"}, id="unparseable_user"),
            pytest.param({"user": '["not", "an", "object"]'}, id="non_object_user"),
            pytest.param({"user": '{"id": 583231}'}, id="user_without_login"),
            pytest.param({"author_association": ""}, id="blank_association"),
        ],
    )
    def test_author_degrades_to_none_without_raising(self, github_issue_record, record_overrides):
        # An author the emitter can't read has to become None rather than drop the issue, so a shape
        # change upstream costs triage the context and nothing else.
        github_issue_record.pop("user")
        github_issue_record.pop("author_association")
        github_issue_record.update(record_overrides)

        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.extra["author_login"] is None
        assert result.extra["author_association"] is None

    def test_logged_records_leave_the_user_object_out(self, github_issue_record):
        # The record reaches the logs on every skipped or malformed issue, and the nested user object
        # carries a numeric id and avatar URLs that identify a person well beyond the handle.
        github_issue_record["body"] = ""

        with patch.object(github_issues_module.logger, "info") as log_info:
            github_issue_emitter(team_id=1, record=github_issue_record)

        assert "user" not in log_info.call_args.kwargs["record"]

    def test_a_failed_record_reaches_the_pipeline_log_without_the_user_object(self, github_issue_record):
        # The emitter raises on malformed labels, and the shared pipeline logs the record it handed
        # over — the whole warehouse row, unless the source declares `user` unloggable.
        github_issue_record["labels"] = "not-json"

        with patch.object(pipeline.logger, "exception") as log_exception:
            _, error_count = build_emitter_outputs(
                team_id=1,
                records=[github_issue_record],
                emitter=GITHUB_ISSUES_CONFIG.emitter,
                unloggable_fields=GITHUB_ISSUES_CONFIG.unloggable_fields,
            )

        assert error_count == 1
        assert "user" not in log_exception.call_args.kwargs["record"]

    def test_labels_parsed_from_json_string(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.extra["labels"] == ["bug", "frontend"]

    @pytest.mark.parametrize("raw_labels", ["not-json", ""])
    def test_raises_on_malformed_labels_json(self, github_issue_record, raw_labels):
        github_issue_record["labels"] = raw_labels
        with pytest.raises(ValueError, match="not valid JSON"):
            github_issue_emitter(team_id=1, record=github_issue_record)

    def test_raises_on_non_array_labels_json(self, github_issue_record):
        github_issue_record["labels"] = '{"not": "an array"}'
        with pytest.raises(ValueError, match="not a JSON array"):
            github_issue_emitter(team_id=1, record=github_issue_record)

    def test_raises_on_unexpected_labels_type(self, github_issue_record):
        github_issue_record["labels"] = 42
        with pytest.raises(ValueError, match="unexpected type"):
            github_issue_emitter(team_id=1, record=github_issue_record)

    def test_labels_defaults_to_empty_when_none(self, github_issue_record):
        github_issue_record["labels"] = None
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.extra["labels"] == []


class TestGithubIssuesConfig:
    def test_partition_field(self):
        assert GITHUB_ISSUES_CONFIG.partition_field == "created_at"

    def test_where_clause_excludes_closed(self):
        assert GITHUB_ISSUES_CONFIG.where_clause is not None
        assert "closed" in GITHUB_ISSUES_CONFIG.where_clause
        assert "NOT IN" in GITHUB_ISSUES_CONFIG.where_clause

    def test_has_actionability_prompt(self):
        assert GITHUB_ISSUES_CONFIG.actionability_prompt is not None
        assert "{description}" in GITHUB_ISSUES_CONFIG.actionability_prompt

    def test_emitter_is_github_issue_emitter(self):
        assert GITHUB_ISSUES_CONFIG.emitter is github_issue_emitter
