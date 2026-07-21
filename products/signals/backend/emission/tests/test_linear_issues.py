import pytest

from products.signals.backend.emission.linear_issues import _linear_team_scope_where, linear_issue_emitter


class TestLinearIssueEmitter:
    def test_emits_signal_for_valid_issue(self, linear_issue_record):
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert result.source_product == "linear"
        assert result.source_type == "issue"
        assert result.source_id == "abc-123-def"
        assert result.weight == 1.0
        assert "Dashboard widgets fail to load" in result.description
        assert "parsing error" in result.description

    @pytest.mark.parametrize("description", [None, ""])
    def test_skips_issue_with_no_description(self, linear_issue_record, description):
        linear_issue_record["description"] = description

        assert linear_issue_emitter(team_id=1, record=linear_issue_record) is None

    @pytest.mark.parametrize(
        "field,value",
        [("id", None), ("id", ""), ("title", None), ("title", "")],
    )
    def test_raises_when_required_field_falsy(self, linear_issue_record, field, value):
        linear_issue_record[field] = value
        with pytest.raises(ValueError, match="empty required field"):
            linear_issue_emitter(team_id=1, record=linear_issue_record)

    def test_raises_for_missing_fields(self):
        with pytest.raises(ValueError, match="missing required field"):
            linear_issue_emitter(team_id=1, record={})

    def test_extra_excludes_description_fields(self, linear_issue_record):
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert "description" not in result.extra
        assert "title" not in result.extra

    def test_labels_parsed_from_json_string(self, linear_issue_record):
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert result.extra["labels"] == ["bug"]

    def test_state_extracted_from_json_string(self, linear_issue_record):
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert result.extra["state_name"] == "In Progress"
        assert result.extra["state_type"] == "started"
        assert "state" not in result.extra

    def test_team_name_extracted_from_json_string(self, linear_issue_record):
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert result.extra["team_name"] == "Engineering"
        assert "team" not in result.extra

    @pytest.mark.parametrize("raw_labels", ["not-json", ""])
    def test_raises_on_malformed_labels_json(self, linear_issue_record, raw_labels):
        linear_issue_record["labels"] = raw_labels
        with pytest.raises(ValueError, match="not valid JSON"):
            linear_issue_emitter(team_id=1, record=linear_issue_record)

    def test_raises_on_unexpected_labels_shape(self, linear_issue_record):
        linear_issue_record["labels"] = '"just a string"'
        with pytest.raises(ValueError, match="unexpected shape"):
            linear_issue_emitter(team_id=1, record=linear_issue_record)

    def test_labels_defaults_to_empty_when_none(self, linear_issue_record):
        linear_issue_record["labels"] = None
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert result.extra["labels"] == []

    @pytest.mark.parametrize("raw_state", ["not-json", ""])
    def test_raises_on_malformed_state_json(self, linear_issue_record, raw_state):
        linear_issue_record["state"] = raw_state
        with pytest.raises(ValueError, match="not valid JSON"):
            linear_issue_emitter(team_id=1, record=linear_issue_record)

    def test_state_defaults_to_none_when_null(self, linear_issue_record):
        linear_issue_record["state"] = None
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert result.extra["state_name"] is None
        assert result.extra["state_type"] is None


class TestLinearTeamScopeWhere:
    # A workspace-wide Linear token imports every team's issues; this builder is the sole guard that
    # keeps Signals from surfacing teams the user didn't opt into. Regressions here re-leak all teams.

    @pytest.mark.parametrize(
        "source_config,expected",
        [
            # No opt-in: unchanged behavior (all teams) — must NOT emit a filter.
            ({}, None),
            ({"linear_team_ids": None}, None),
            ({"linear_team_ids": []}, None),
            (
                {"linear_team_ids": ["team-1", "team-2"]},
                "JSONExtractString(team, 'id') IN ('team-1', 'team-2')",
            ),
            # Fail closed: an opt-in with no usable IDs matches nothing rather than widening to all teams.
            ({"linear_team_ids": ["bad id!"]}, "JSONExtractString(team, 'id') IN ('')"),
            ({"linear_team_ids": ["good-1", "bad;drop"]}, "JSONExtractString(team, 'id') IN ('good-1')"),
            # Malformed config (not a list) is ignored, leaving all-teams behavior.
            ({"linear_team_ids": "team-1"}, None),
        ],
    )
    def test_builds_scope_clause(self, source_config, expected):
        assert _linear_team_scope_where(source_config) == expected
