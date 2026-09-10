from typing import Any

import pytest

from products.signals.backend.emission._common import make_flat_emitter, parse_json_list


class TestParseJsonList:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, []),
            ([], []),
            (["a", "b"], ["a", "b"]),
            ('["a", "b"]', ["a", "b"]),
            ("not-json", []),
            ("", []),
            ('{"not": "an array"}', []),
            (42, []),
        ],
    )
    def test_parses_or_falls_back_to_empty(self, raw, expected):
        assert parse_json_list(raw) == expected


class TestMakeFlatEmitter:
    def _emitter(self, **kwargs):
        defaults: dict[str, Any] = {
            "source_product": "acme",
            "source_type": "ticket",
            "id_field": "id",
            "title_field": "subject",
            "extra_fields": ("status", "tags"),
            "json_list_fields": ("tags",),
        }
        defaults.update(kwargs)
        return make_flat_emitter(**defaults)

    def test_emits_title_only_when_no_body_field(self):
        out = self._emitter()(1, {"id": 7, "subject": "Broken", "status": "open", "tags": '["a"]'})
        assert out is not None
        assert out.source_product == "acme"
        assert out.source_type == "ticket"
        assert out.source_id == "7"
        assert out.description == "Broken"
        assert out.weight == 1.0

    def test_appends_body_when_present(self):
        emitter = self._emitter(body_field="body")
        out = emitter(1, {"id": 7, "subject": "Broken", "body": "details", "status": "open", "tags": None})
        assert out is not None
        assert out.description == "Broken\ndetails"

    def test_title_only_when_body_empty(self):
        emitter = self._emitter(body_field="body")
        out = emitter(1, {"id": 7, "subject": "Broken", "body": "", "status": "open", "tags": None})
        assert out is not None
        assert out.description == "Broken"

    @pytest.mark.parametrize("empty_title", [None, ""])
    def test_returns_none_when_title_empty(self, empty_title):
        assert self._emitter()(1, {"id": 7, "subject": empty_title, "status": "x", "tags": None}) is None

    def test_returns_none_when_id_falsy(self):
        assert self._emitter()(1, {"id": 0, "subject": "Broken", "status": "x", "tags": None}) is None

    def test_raises_when_required_column_absent(self):
        with pytest.raises(ValueError, match="missing required field"):
            self._emitter()(1, {"subject": "Broken"})

    def test_extra_is_limited_to_declared_fields_and_coerced(self):
        out = self._emitter()(1, {"id": 7, "subject": "Broken", "status": 4, "tags": '["a", "b"]', "secret": "x"})
        assert out is not None
        assert set(out.extra.keys()) == {"status", "tags"}
        assert out.extra["status"] == "4"  # scalar coerced to str
        assert out.extra["tags"] == ["a", "b"]  # json list parsed
        assert "secret" not in out.extra

    def test_missing_extra_field_defaults_to_none(self):
        out = self._emitter()(1, {"id": 7, "subject": "Broken", "tags": None})
        assert out is not None
        assert out.extra["status"] is None
        assert out.extra["tags"] == []
