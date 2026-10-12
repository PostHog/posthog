"""Grafana template variables, resolved to the values that the dashboard JSON saved as current."""

from __future__ import annotations

import re
from typing import Any

from posthog.dataclasses import frozen

_REFERENCE = re.compile(
    r"\$\{(?P<braced>[A-Za-z0-9_]+)(?::(?P<braced_format>[A-Za-z0-9_]+))?\}"
    r"|\[\[(?P<bracketed>[A-Za-z0-9_]+)(?::(?P<bracketed_format>[A-Za-z0-9_]+))?\]\]"
    r"|\$(?P<plain>[A-Za-z0-9_]+)"
)
# The range rewrite handles these, so the substitution must leave them in place.
GRAFANA_RANGE_VARIABLES = frozenset({"__rate_interval", "__interval", "__range", "__auto"})
_REGEX_SPECIAL = set("\\^$.|?*+()[]{}")
_SKIPPED_TYPES = frozenset({"datasource", "adhoc", "groupby"})
ALL_VALUE = "$__all"


@frozen
class Variable:
    values: tuple[str, ...]
    is_all: bool
    all_value: str | None
    options: tuple[str, ...]


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if item is not None)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return (str(value),)
    return ()


def regex_escape(value: str) -> str:
    # The value lands inside a double-quoted PromQL string, so each regex escape needs a doubled backslash.
    return "".join(f"\\\\{char}" if char in _REGEX_SPECIAL else char for char in value)


class TemplateVariables:
    def __init__(self, variables: dict[str, Variable]) -> None:
        self._variables = variables

    @classmethod
    def from_templating(cls, items: Any) -> TemplateVariables:
        variables: dict[str, Variable] = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            kind = item.get("type")
            if kind in _SKIPPED_TYPES:
                continue
            raw_current = item.get("current")
            current: dict[str, Any] = raw_current if isinstance(raw_current, dict) else {}
            values = _strings(current.get("value"))
            if not values and kind in ("constant", "textbox"):
                values = _strings(item.get("query"))
            if kind == "interval":
                # An "auto" interval resolves per panel in Grafana, which is the query step here.
                values = tuple("$__interval" if value.startswith("$__auto") else value for value in values)
            options = tuple(
                str(option.get("value"))
                for option in item.get("options") or []
                if isinstance(option, dict) and option.get("value") not in (None, ALL_VALUE)
            )
            all_value = item.get("allValue") if isinstance(item.get("allValue"), str) else None
            is_all = ALL_VALUE in values or (current.get("text") == "All" and bool(item.get("includeAll")))
            variables[item["name"]] = Variable(
                values=tuple(value for value in values if value != ALL_VALUE),
                is_all=is_all,
                all_value=all_value or None,
                options=options,
            )
        return cls(variables)

    def summary(self) -> dict[str, str]:
        return {
            name: "All" if variable.is_all else ", ".join(variable.values) for name, variable in self._variables.items()
        }

    def substitute(self, expr: str) -> tuple[str, list[str]]:
        """Replace variable references with their saved values. Also returns the names it could not resolve."""
        unresolved: list[str] = []

        def replace(match: re.Match[str]) -> str:
            name = match.group("braced") or match.group("bracketed") or match.group("plain")
            value_format = match.group("braced_format") or match.group("bracketed_format")
            if name in GRAFANA_RANGE_VARIABLES:
                return match.group(0)
            variable = self._variables.get(name)
            if variable is None or (not variable.values and not variable.is_all):
                unresolved.append(name)
                return match.group(0)
            return self._format(variable, value_format)

        return _REFERENCE.sub(replace, expr), list(dict.fromkeys(unresolved))

    @staticmethod
    def _format(variable: Variable, value_format: str | None) -> str:
        if variable.is_all:
            if variable.all_value is not None:
                return variable.all_value
            if not variable.options:
                return ".*"
            values = variable.options
            value_format = value_format or "regex"
        else:
            values = variable.values
        if value_format in ("raw", "text", "csv"):
            return ",".join(values)
        if value_format == "pipe":
            return "|".join(values)
        if value_format == "regex" or len(values) > 1:
            escaped = [regex_escape(value) for value in values]
            return f"({'|'.join(escaped)})" if len(escaped) > 1 else escaped[0]
        return values[0]
