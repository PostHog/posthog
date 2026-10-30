#!/usr/bin/env python3
"""Rank saved repository candidates for a scout without network access or cloning."""

from __future__ import annotations

import re
import sys
import json
import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

STOP_WORDS = frozenset(
    "a an the and or of to in on for with from by at as is are was were be been being it its "
    "this that these those your our you we they their not no can do does into via using use "
    "only all any more most first http https www com github readme".split()
)
REPOSITORY_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def string_field(data: dict[str, object], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def string_list(data: dict[str, object], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{key} must be a list of nonempty strings")
    return value


def repository_name(value: str) -> str:
    if not REPOSITORY_NAME.fullmatch(value) or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError(f"Invalid repository name: {value!r}")
    return value.lower()


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("last_human_activity must include a timezone")
    return parsed.astimezone(UTC)


def activity_count(data: dict[str, object]) -> int | None:
    count = data.get("human_merged_prs_30d")
    if count is None:
        return None
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("human_merged_prs_30d must be a nonnegative integer or null")
    return count


@dataclass(frozen=True, kw_only=True, slots=True)
class Repository:
    full_name: str
    text: str
    excluded_reason: str | None
    project_matches: list[str]
    confirmed_fix_urls: list[str]
    human_merged_prs_30d: int | None
    last_human_activity: datetime | None

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Repository:
        full_name = repository_name(string_field(data, "full_name"))
        flags = ("archived", "fork", "template", "mirror")
        for flag in flags:
            if not isinstance(data.get(flag, False), bool):
                raise ValueError(f"{flag} must be a boolean")
        last_activity = string_field(data, "last_human_activity") if data.get("last_human_activity") is not None else ""
        return cls(
            full_name=full_name,
            text=" ".join(
                (full_name.split("/")[1], string_field(data, "description"), string_field(data, "readme")[:2000])
            ),
            excluded_reason=next((flag for flag in flags if data.get(flag)), None),
            project_matches=string_list(data, "project_matches"),
            confirmed_fix_urls=string_list(data, "confirmed_fix_urls"),
            human_merged_prs_30d=activity_count(data),
            last_human_activity=timestamp(last_activity) if last_activity else None,
        )

    def exclusion(self, allowed: set[str], pinned: bool) -> str | None:
        if self.full_name not in allowed:
            return "not_allowed"
        return None if pinned else self.excluded_reason


def tokens(text: str, ignored: set[str]) -> set[str]:
    text = re.sub(r"https?://\S+|!\[[^\]]*\]\([^)]*\)|<[^>]+>", " ", text)
    return set(re.findall(r"[a-z][a-z0-9]+", text.lower())) - STOP_WORDS - ignored


@dataclass(frozen=True, kw_only=True, slots=True)
class RankedRepository:
    repository: Repository
    pinned: bool
    metadata_similarity: float
    matched_terms: list[str]

    @property
    def confidence(self) -> str:
        if self.pinned or self.repository.project_matches:
            return "high"
        return "medium" if self.repository.confirmed_fix_urls else "low"

    def sort_key(self) -> tuple[bool, bool, bool, float, int, datetime]:
        repo = self.repository
        return (
            self.pinned,
            bool(repo.project_matches),
            bool(repo.confirmed_fix_urls),
            self.metadata_similarity,
            repo.human_merged_prs_30d if repo.human_merged_prs_30d is not None else -1,
            repo.last_human_activity or datetime.min.replace(tzinfo=UTC),
        )

    @classmethod
    def score(cls, repo: Repository, context_terms: set[str], ignored: set[str], pinned: bool) -> RankedRepository:
        repo_terms = tokens(repo.text, ignored)
        matched = sorted(context_terms & repo_terms)
        union = context_terms | repo_terms
        return cls(
            repository=repo,
            pinned=pinned,
            metadata_similarity=len(matched) / len(union) if union else 0.0,
            matched_terms=matched,
        )

    def to_json(self) -> dict[str, object]:
        repo = self.repository
        missing = []
        if repo.human_merged_prs_30d is None:
            missing.append("human_merged_prs_30d")
        if repo.last_human_activity is None:
            missing.append("last_human_activity")
        return {
            "repository": repo.full_name,
            "confidence": self.confidence,
            "pinned": self.pinned,
            "project_matches": repo.project_matches,
            "confirmed_fix_urls": repo.confirmed_fix_urls,
            "metadata_similarity": self.metadata_similarity,
            "matched_terms": self.matched_terms,
            "human_merged_prs_30d": repo.human_merged_prs_30d,
            "last_human_activity": repo.last_human_activity.isoformat() if repo.last_human_activity else None,
            "missing_evidence": missing,
            "needs_project_evidence": not (self.pinned or repo.project_matches),
        }


def load_repositories(payload: dict[str, object]) -> dict[str, Repository]:
    candidates = payload.get("repositories")
    if not isinstance(candidates, list):
        raise ValueError("repositories must be a list")
    repositories: dict[str, Repository] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Each repository must be an object")
        repo = Repository.from_json(candidate)
        if repo.full_name in repositories:
            raise ValueError(f"Duplicate repository: {repo.full_name}")
        repositories[repo.full_name] = repo
    return repositories


class Ranking(TypedDict):
    ranking_version: int
    repositories: list[dict[str, object]]
    excluded: list[dict[str, str]]
    pinned_without_metadata: list[str]


def rank_repositories(payload: dict[str, object], limit: int = 5) -> Ranking:
    if limit < 1:
        raise ValueError("limit must be positive")
    if "allowed_repositories" not in payload:
        raise ValueError("allowed_repositories is required")
    allowed = {repository_name(name) for name in string_list(payload, "allowed_repositories")}
    pinned = {repository_name(name) for name in string_list(payload, "pinned_repositories")}
    ignored = {term.lower() for term in string_list(payload, "ignore_terms")} | {name.split("/")[0] for name in allowed}
    context_terms = tokens(string_field(payload, "context"), ignored)
    repositories = load_repositories(payload)
    ranked: list[RankedRepository] = []
    excluded: list[dict[str, str]] = []
    for repo in repositories.values():
        is_pinned = repo.full_name in pinned
        reason = repo.exclusion(allowed, is_pinned)
        if reason:
            excluded.append({"repository": repo.full_name, "reason": reason})
            continue
        ranked.append(RankedRepository.score(repo, context_terms, ignored, is_pinned))
    ranked.sort(key=lambda item: item.repository.full_name)
    ranked.sort(key=RankedRepository.sort_key, reverse=True)
    return {
        "ranking_version": 1,
        "repositories": [item.to_json() for item in ranked[:limit]],
        "excluded": sorted(excluded, key=lambda item: item["repository"]),
        "pinned_without_metadata": sorted((pinned & allowed) - repositories.keys()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="Saved project context and repository evidence as JSON"
    )
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Input must be an object")
        result = rank_repositories(payload, args.limit)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
