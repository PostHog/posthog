import pytest

from products.signals.backend.emission.jira_issues import jira_issue_emitter


class TestJiraIssueEmitter:
    def test_emits_signal_for_valid_issue(self, jira_issue_record):
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.source_product == "jira"
        assert result.source_type == "issue"
        assert result.source_id == "10042"
        assert result.weight == 1.0
        assert "Dashboard widgets fail to load" in result.description
        assert "parsing error" in result.description

    @pytest.mark.parametrize("description", [None, "", "not-json", "{}"])
    def test_falls_back_to_summary_when_no_body(self, jira_issue_record, description):
        jira_issue_record["description"] = description
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.description == jira_issue_record["summary"]

    @pytest.mark.parametrize(
        "field,value",
        [("id", None), ("id", ""), ("summary", None), ("summary", "")],
    )
    def test_raises_when_required_field_falsy(self, jira_issue_record, field, value):
        jira_issue_record[field] = value
        with pytest.raises(ValueError, match="empty required field"):
            jira_issue_emitter(team_id=1, record=jira_issue_record)

    @pytest.mark.parametrize("missing", [{}, {"id": "1"}, {"id": "1", "key": "ENG-1"}])
    def test_raises_for_missing_fields(self, missing):
        with pytest.raises(ValueError, match="missing required field"):
            jira_issue_emitter(team_id=1, record=missing)

    def test_extra_excludes_description_and_summary(self, jira_issue_record):
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert "description" not in result.extra
        assert "summary" not in result.extra

    def test_labels_parsed_from_json_string(self, jira_issue_record):
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.extra["labels"] == ["bug", "frontend"]

    @pytest.mark.parametrize("raw_labels", [None, "", "not-json", '"a string"', "[]"])
    def test_labels_lenient_on_missing_or_malformed(self, jira_issue_record, raw_labels):
        jira_issue_record["labels"] = raw_labels
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.extra["labels"] == []

    def test_status_priority_assignee_in_extra(self, jira_issue_record):
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.extra["status"] == "In Progress"
        assert result.extra["priority"] == "High"
        assert result.extra["assignee"] == "Jane Doe"

    @pytest.mark.parametrize("field", ["status", "priority", "assignee"])
    def test_optional_extra_fields_default_to_none(self, jira_issue_record, field):
        jira_issue_record[field] = ""
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.extra[field] is None

    def test_browse_url_built_from_self_url(self, jira_issue_record):
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.extra["url"] == "https://acme.atlassian.net/browse/ENG-42"

    @pytest.mark.parametrize("self_url", [None, ""])
    def test_url_none_when_self_url_missing(self, jira_issue_record, self_url):
        jira_issue_record["self_url"] = self_url
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.extra["url"] is None

    def test_key_included_in_extra(self, jira_issue_record):
        result = jira_issue_emitter(team_id=1, record=jira_issue_record)

        assert result is not None
        assert result.extra["key"] == "ENG-42"
