from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, cast

from django.db.models import QuerySet

from pydantic import JsonValue
from rest_framework import exceptions
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from posthog.models import User

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore, TrialReport
from products.signals.backend.serializers import ReportMetricListSerializer

if TYPE_CHECKING:
    from products.signals.backend.views import SignalReportViewSet


class TrialInboxReads:
    SUPPORTED_LIST_PARAMETERS = frozenset(
        {
            "search",
            "status",
            "include_all_statuses",
            "source_product",
            "source_id",
            "scout",
            "scout_prefix",
            "count_only",
            "ordering",
            "sort",
            "limit",
            "offset",
            "format",
        }
    )
    _EDITABLE_FIELDS = frozenset({"title", "summary", "charts", "metrics", "suggested_prompts"})

    def __init__(self, view: SignalReportViewSet, store: ScoutTrialStore) -> None:
        self.view = view
        self.store = store

    def _decorate(self, report: TrialReport, document: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if report.evidence:
            products = document.get("source_products")
            source_products = (
                {"signals_scout", *(str(item) for item in products)}
                if isinstance(products, list)
                else {"signals_scout"}
            )
            document["source_products"] = cast(list[JsonValue], sorted(source_products))
            document["scout_name"] = self.store.run.skill_name
        for artefact in reversed(report.artefacts):
            if artefact["type"] != "suggested_reviewers":
                continue
            entries = artefact["content"]
            if isinstance(entries, list):
                user = cast(User, self.view.request.user)
                login = self.view._get_github_login(user)
                document["is_suggested_reviewer"] = any(
                    isinstance(entry, dict)
                    and (entry.get("user_uuid") == str(user.uuid) or (login and entry.get("github_login") == login))
                    for entry in entries
                )
            break
        if document.get("status") == "failed" or (
            document.get("status") == "ready" and document.get("actionability") == "not_actionable"
        ):
            document["is_suggested_reviewer"] = False
        return document

    @classmethod
    def overlay(cls, report: TrialReport, live: Mapping[str, object] | None = None) -> dict[str, JsonValue]:
        if report.source_report_id is None:
            return dict(report.document)
        if live is None:
            raise exceptions.NotFound()
        document = cast(dict[str, JsonValue], dict(live))
        changed_fields = {"signal_count", "total_weight", "collapsed_note_count", "updated_at"}
        for edit in report.edits:
            changed_fields.update(field for field in cls._EDITABLE_FIELDS if edit.get(field) is not None)
            if edit.get("repository") is not None:
                changed_fields.add("repo_slug")
        for field in changed_fields:
            if field in report.document:
                document[field] = report.document[field]
        count = live.get("artefact_count", 0)
        document["artefact_count"] = (count if isinstance(count, int) else 0) + len(report.artefacts)
        return document

    def detail(self, report_id: str) -> dict[str, JsonValue] | None:
        report = self.store.get_report(report_id)
        if report is None:
            return None
        if report.source_report_id is not None:
            original = self.view.get_object()
            data = self.view.get_serializer(original, context=self.view._enriched_report_context(original)).data
            return self._decorate(report, self.overlay(report, data))
        if report.document.get("status") not in self.view._visible_statuses():
            raise exceptions.NotFound()
        return self._decorate(report, self.overlay(report))

    def _validate_parameters(self) -> None:
        unsupported = set(self.view.request.query_params) - self.SUPPORTED_LIST_PARAMETERS
        if unsupported:
            reason = f"This scout run cannot compare inbox filters: {', '.join(sorted(unsupported))}."
            self.store.invalidate(reason)
            raise exceptions.ValidationError({"detail": reason})

    @staticmethod
    def _tokens(value: str | None) -> list[str]:
        return [part.strip() for part in (value or "").split(",") if part.strip()]

    def _matches_sources(self, report: TrialReport, original: QuerySet[SignalReport]) -> bool:
        query = self.view.request.query_params
        original_id = report.source_report_id
        evidence = report.evidence
        if self._tokens(query.get("source_id")):
            source_ids = self._tokens(query.get("source_id"))
            product = (query.get("source_product") or "").strip()
            if not any(row.get("source_product") == product and row.get("source_id") in source_ids for row in evidence):
                if (
                    original_id is None
                    or not self.view._apply_signal_report_source_id_filter(original).filter(pk=original_id).exists()
                ):
                    return False
        elif self._tokens(query.get("source_product")):
            products = self._tokens(query.get("source_product"))
            if not any(row.get("source_product") in products for row in evidence):
                if (
                    original_id is None
                    or not self.view._apply_signal_report_source_product_filter(original)
                    .filter(pk=original_id)
                    .exists()
                ):
                    return False
        scout_names = self._tokens(query.get("scout"))
        prefix = (query.get("scout_prefix") or "").strip()
        for requested, matches, apply_filter in (
            (bool(scout_names), self.store.run.skill_name in scout_names, self.view._apply_signal_report_scout_filter),
            (
                bool(prefix),
                self.store.run.skill_name.startswith(prefix),
                self.view._apply_signal_report_scout_prefix_filter,
            ),
        ):
            if requested and not (evidence and matches):
                if original_id is None or not apply_filter(original).filter(pk=original_id).exists():
                    return False
        return True

    def _private_documents(self, reports: Sequence[TrialReport]) -> list[dict[str, JsonValue]]:
        source_ids = [report.source_report_id for report in reports if report.source_report_id is not None]
        originals = self.view._scope_signal_report_queryset(
            SignalReport.objects.filter(team_id=self.store.run.team_id, id__in=source_ids)
        )
        originals = self.view._annotate_artefact_count(originals)
        originals = self.view._annotate_channel_id(originals)
        originals = self.view._prefetch_signal_report_priority_artefacts(originals)
        originals = self.view._annotate_is_suggested_reviewer(originals)
        live = {str(row["id"]): row for row in self.view._serialize_report_list(list(originals))}
        statuses = self.view._visible_statuses()
        search = (self.view.request.query_params.get("search") or "").casefold()
        result = []
        for report in reports:
            if report.source_report_id is not None and report.source_report_id not in live:
                continue
            document = self._decorate(report, self.overlay(report, live.get(report.source_report_id or "")))
            if document.get("status") not in statuses:
                continue
            if search and not any(search in str(document.get(field, "")).casefold() for field in ("title", "summary")):
                continue
            if not self._matches_sources(report, originals):
                continue
            metrics = document.get("metrics")
            if isinstance(metrics, list):
                document["metrics"] = cast(list[JsonValue], ReportMetricListSerializer(metrics, many=True).data)
            result.append(document)
        return result

    @staticmethod
    def _sort_value(document: Mapping[str, object], field: str) -> str | int | float | datetime:
        if field == "pipeline_status_rank":
            status = document.get("status")
            if status == "ready":
                return 1 if document.get("actionability") == "not_actionable" else 0
            return {
                "pending_input": 2,
                "in_progress": 3,
                "candidate": 4,
                "potential": 5,
                "failed": 6,
                "resolved": 7,
                "suppressed": 8,
                "deleted": 9,
            }.get(str(status), 50)
        if field == "priority_sort_rank":
            priority = document.get("priority")
            return (
                {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}[str(priority)]
                if priority in ["P0", "P1", "P2", "P3", "P4"]
                else 5
            )
        value = document.get(field)
        if field in {"created_at", "updated_at"}:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if field in {"is_suggested_reviewer", "signal_count", "total_weight"}:
            return value if isinstance(value, (int, float)) else 0
        return str(value or "")

    def list(self) -> Response:
        self._validate_parameters()
        count_only = self.view._count_only_requested()
        queryset = self.view.filter_queryset(self.view.get_queryset())
        private = self.store.reports()
        documents = self._private_documents(private)
        queryset = queryset.exclude(id__in=[report.id for report in private])
        count = queryset.count() + len(documents)
        if count_only:
            return Response({"count": count, "next": None, "previous": None, "results": []})
        paginator = self.view.paginator
        if not isinstance(paginator, LimitOffsetPagination):
            raise exceptions.ValidationError({"detail": "This scout run requires limit/offset inbox pagination."})
        paginator.request = self.view.request
        paginator.limit = paginator.get_limit(self.view.request)
        paginator.offset = paginator.get_offset(self.view.request)
        paginator.count = count
        limit = paginator.limit or count
        # At most this run's private reports can shift a production row across the requested offset.
        start = max(0, paginator.offset - len(documents))
        production = list(queryset[start : paginator.offset + limit])
        merged: list[Mapping[str, object]] = [*self.view._serialize_report_list(production), *documents]
        clauses = self.view._parse_signal_report_ordering()
        if not any(clause.lstrip("-") == "id" for clause in clauses):
            clauses.append("id")
        for clause in reversed(clauses):
            merged.sort(key=lambda row: self._sort_value(row, clause.lstrip("-")), reverse=clause.startswith("-"))
        offset = paginator.offset - start
        return paginator.get_paginated_response(merged[offset : offset + limit])


def private_report_artefacts(store: ScoutTrialStore, report_id: str) -> list[SignalReportArtefact]:
    report = store.get_report(report_id)
    if report is None:
        return []
    if (
        report.source_report_id is not None
        and not SignalReport.objects.filter(team_id=store.run.team_id, id=report.source_report_id)
        .exclude(status=SignalReport.Status.DELETED)
        .exists()
    ):
        raise exceptions.NotFound()
    return [
        SignalReportArtefact(
            id=record["id"],
            team_id=store.run.team_id,
            report_id=report_id,
            type=str(record["type"]),
            content=json.dumps(record["content"]),
            created_at=datetime.fromisoformat(str(record["created_at"])),
            updated_at=datetime.fromisoformat(str(record["updated_at"])),
            actor_kind="task",
            task_id=store.run.task_run.task_id,
        )
        for record in report.artefacts
    ]
