from __future__ import annotations

import re
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import groupby
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4, uuid5

from products.posthog_ai.eval_harness.environment.schema import EnvironmentRow, EnvironmentTextPolicy

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet


_UUID_TEXT = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


class EnvironmentTransform:
    def __init__(
        self,
        *,
        source_cutoff: datetime,
        target_cutoff: datetime,
        record_ids: Sequence[UUID],
        namespace: UUID | None = None,
        time_strings: Sequence[str] = (),
        string_replacements: Mapping[str, str] | None = None,
    ) -> None:
        for cutoff in (source_cutoff, target_cutoff):
            if cutoff.tzinfo is None or cutoff.utcoffset() is None:
                raise ValueError("Environment cutoffs must include a timezone.")
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Environment record IDs must be unique.")
        policy = EnvironmentTextPolicy(
            time_strings=list(time_strings), string_replacements=dict(string_replacements or {})
        )
        self.namespace = namespace or uuid4()
        self.delta = target_cutoff.astimezone(UTC) - source_cutoff.astimezone(UTC)
        self.ids = {identifier: uuid5(self.namespace, str(identifier)) for identifier in record_ids}
        self.replacements = self._time_replacements(policy.time_strings)
        self.replacements.update(policy.string_replacements)
        self._text_pattern = self._replacement_pattern(self.replacements, set(policy.time_strings))

    def _time_replacements(self, time_strings: Sequence[str]) -> dict[str, str]:
        replacements: dict[str, str] = {}
        for value in time_strings:
            if not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?", value
            ):
                raise ValueError("A declared time string is not a supported ISO date or timestamp.")
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as error:
                raise ValueError("A declared time string is not a valid ISO date or timestamp.") from error
            shifted = parsed.replace(tzinfo=parsed.tzinfo or UTC) + self.delta
            if len(value) == 10:
                replacements[value] = shifted.date().isoformat()
                continue
            time_part = value[11:].removesuffix("Z")
            fraction = re.search(r"\.(\d+)", time_part)
            timespec = "microseconds" if fraction else "seconds" if len(value) >= 19 and value[16] == ":" else "minutes"
            rendered = shifted.isoformat(sep=value[10], timespec=timespec)
            if fraction:
                precision = len(fraction.group(1))

                def truncate_fraction(match: re.Match[str], digits: int = precision) -> str:
                    return "." + match.group(1)[:digits]

                rendered = re.sub(r"\.(\d{6})", truncate_fraction, rendered)
            if value.endswith("Z"):
                rendered = rendered.removesuffix("+00:00") + "Z"
            elif parsed.tzinfo is None:
                rendered = rendered.removesuffix("+00:00")
            replacements[value] = rendered
        return replacements

    @staticmethod
    def _replacement_pattern(replacements: Mapping[str, str], time_strings: set[str]) -> re.Pattern[str] | None:
        if not replacements:
            return None
        alternatives = []
        ordered_keys = sorted(replacements, key=len, reverse=True)
        for is_time, keys in groupby(ordered_keys, key=lambda key: key in time_strings):
            if is_time:
                dates = [re.escape(key) + (r"(?![T ]\d{2}:\d{2})" if len(key) == 10 else "") for key in keys]
                alternatives.append(r"(?<![\w/-])(?:" + "|".join(dates) + r")(?![\w/+-]|\.\d)")
            else:
                alternatives.extend(re.escape(key) for key in keys)
        return re.compile("|".join(alternatives))

    def identity(self, value: UUID) -> UUID:
        return self.ids.get(value) or uuid5(self.namespace, str(value))

    def text(self, value: str) -> str:
        value = _UUID_TEXT.sub(lambda match: str(self.ids.get(UUID(match.group(0)), match.group(0))), value)
        if self._text_pattern:
            value = self._text_pattern.sub(lambda match: self.replacements[match.group(0)], value)
        return value

    def value(self, value: object) -> object:
        if isinstance(value, UUID):
            return self.identity(value)
        if isinstance(value, datetime):
            return value + self.delta
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            transformed: dict[str, object] = {}
            for key, nested in value.items():
                transformed_key = self.text(key)
                if transformed_key in transformed:
                    raise ValueError("Environment text replacements cause a dictionary key collision.")
                transformed[transformed_key] = self.value(nested)
            return transformed
        if isinstance(value, list):
            return [self.value(nested) for nested in value]
        if value is None or isinstance(value, bool | int | float):
            return value
        raise TypeError(f"Unsupported environment value: {type(value).__name__}")

    def insert(
        self,
        queryset: QuerySet[Model],
        model: type[Model],
        source: EnvironmentRow,
        team_id: int,
        *,
        overrides: Mapping[str, object] | None = None,
    ) -> None:
        from django.core.serializers.json import DjangoJSONEncoder  # noqa: PLC0415 — only restoration needs Django
        from django.db.models import JSONField  # noqa: PLC0415 — only restoration needs Django

        data = cast(dict[str, object], self.value(source.model_dump(exclude={"team_id", "created_at", "updated_at"})))
        data.update(overrides or {})
        for field in model._meta.fields:
            if isinstance(field, JSONField) and field.name in data:
                data[field.name] = json.loads(json.dumps(data[field.name], cls=DjangoJSONEncoder))
        row = model(team_id=team_id, **data)
        queryset.bulk_create([row])
        dates = {"created_at": source.created_at + self.delta}
        if any(field.name == "updated_at" for field in model._meta.fields):
            dates["updated_at"] = (source.updated_at or source.created_at) + self.delta
        queryset.filter(id=row.pk).update(**dates)
