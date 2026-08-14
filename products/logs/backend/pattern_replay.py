"""Replay a fixed corpus of log bodies through the miner and measure the result.

Masking and truncation interact: every masking change shifts string lengths, which moves
the truncation cut point. So a miner change cannot be judged by reading its output — it
needs the same corpus measured before and after. This module is that measurement.

Compare two tunings in one run:

    python -m products.logs.backend.pattern_replay corpora/edge.jsonl --compare truncate=1024

Compare a code change across two runs, one per branch:

    python -m products.logs.backend.pattern_replay corpora/edge.jsonl --save before.json
    python -m products.logs.backend.pattern_replay corpora/edge.jsonl --baseline before.json

A corpus is one JSON object per line, each with at least a `body`; `service_name`,
`severity_text`, and `timestamp` are optional. Capture one per service from query-logs rows,
and keep it under `corpora/`, which is gitignored — corpora hold real log bodies and this
repository is public. `test/fixtures/pattern_replay_sample.jsonl` is invented data, small
enough to smoke-test the command but too small to measure a change against.
"""

import os
import json
import argparse
import datetime as dt
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from posthog.dataclasses import frozen

from products.logs.backend.log_patterns import LogSample, _env, mine_patterns

# Mining reads timestamps only to report first/last seen, which the harness does not score.
# A corpus may therefore omit them, and every such row shares this stamp.
_UNDATED = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)

# mine_patterns defaults to the 200 rows the API renders. Measuring through that cap would
# read a 400-template corpus as 200 and hide exactly the fragmentation this tool exists to
# find, so the harness asks for every cluster Drain kept.
_UNCAPPED = 1_000_000


@frozen
class _TuningKnob:
    env_var: str
    default: float | int
    cast: Callable[[str], Any]


# One row per ReplayConfig field, so reading the tuning, overriding it from the command
# line, and printing it all stay derived from the same place.
_TUNING = {
    "truncate": _TuningKnob(env_var="LOGS_PATTERNS_BODY_TRUNCATE", default=512, cast=int),
    "sim_th": _TuningKnob(env_var="LOGS_PATTERNS_SIM_TH", default=0.4, cast=float),
    "depth": _TuningKnob(env_var="LOGS_PATTERNS_DEPTH", default=4, cast=int),
    "max_clusters": _TuningKnob(env_var="LOGS_PATTERNS_MAX_CLUSTERS", default=1000, cast=int),
}


@frozen
class ReplayConfig:
    truncate: int
    sim_th: float
    depth: int
    max_clusters: int

    @classmethod
    def from_env(cls) -> "ReplayConfig":
        # Read through the miner's own _env, so a value it rejects and defaults is recorded
        # here as the default it actually mined with, not the string the environment held.
        return cls(**{field: _env(knob.env_var, knob.default, knob.cast) for field, knob in _TUNING.items()})  # type: ignore[arg-type]


@frozen
class ServiceReport:
    service_name: str
    sample_count: int
    template_count: int
    prefix_duplicate_count: int


@frozen
class ReplayReport:
    sample_count: int
    template_count: int
    prefix_duplicate_count: int
    config: ReplayConfig
    # Each service mined alone, alongside the blended figures above. Production mines every
    # service together, so the blended number is the one that ships — but fragmentation is a
    # property of one service's body shape, and blending buries which service owns it.
    services: tuple[ServiceReport, ...] = ()


@frozen
class ReplayDiff:
    template_delta: int
    prefix_duplicate_delta: int
    # Config keys whose values differ between the two runs. Non-empty means the deltas
    # above measure the config change as much as the code change, so they answer nothing.
    config_mismatch: tuple[str, ...]


def count_prefix_duplicates(templates: list[str]) -> int:
    """Count templates that are a strict prefix of another template.

    The headline metric. One log statement whose body is cut at a drifting offset lands in
    several clusters whose templates are prefixes of each other, so this counts how badly
    the corpus is fragmenting. Raw template count alone hides that: a change can trade
    character-level fragments for word-level ones and leave the total flat.
    """
    ordered = sorted(templates)
    # Only neighbors need comparing. If a sorts before c and is a prefix of it, anything
    # sorting between them also starts with a, so a prefix relation always shows up
    # adjacent — no pair is missed by skipping the quadratic sweep.
    return sum(1 for a, b in zip(ordered, ordered[1:]) if b != a and b.startswith(a))


def load_corpus(path: Path) -> list[LogSample]:
    """Read a corpus of log rows, one JSON object per line.

    Only `body` is required. Corpora are captured from real streams and are never checked
    in, so the reader stays tolerant of whatever the capture step left behind.
    """
    samples = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        raw_timestamp = row.get("timestamp")
        samples.append(
            LogSample(
                body=row["body"],
                severity_text=row.get("severity_text", "info"),
                service_name=row.get("service_name", "unknown"),
                timestamp=dt.datetime.fromisoformat(raw_timestamp) if raw_timestamp else _UNDATED,
            )
        )
    return samples


def _mine_templates(samples: list[LogSample]) -> list[str]:
    return [pattern.pattern for pattern in mine_patterns(samples, max_patterns=_UNCAPPED)]


def measure(samples: list[LogSample]) -> ReplayReport:
    """Mine a corpus and score how badly it fragments, overall and per service."""
    by_service: dict[str, list[LogSample]] = defaultdict(list)
    for sample in samples:
        by_service[sample.service_name].append(sample)

    services = []
    for name, owned in sorted(by_service.items()):
        owned_templates = _mine_templates(owned)
        services.append(
            ServiceReport(
                service_name=name,
                sample_count=len(owned),
                template_count=len(owned_templates),
                prefix_duplicate_count=count_prefix_duplicates(owned_templates),
            )
        )

    templates = _mine_templates(samples)
    return ReplayReport(
        sample_count=len(samples),
        template_count=len(templates),
        prefix_duplicate_count=count_prefix_duplicates(templates),
        config=ReplayConfig.from_env(),
        services=tuple(services),
    )


def diff_reports(baseline: ReplayReport, candidate: ReplayReport) -> ReplayDiff:
    """Compare two runs, refusing to imply a delta the numbers cannot support.

    A miner change is judged by re-running the same corpus, so the tuning has to be held
    still across both runs. When it was not, the deltas still compute — they just no longer
    isolate the change, which is why the mismatch travels with them instead of being dropped.
    """
    mismatch = tuple(
        field.name
        for field in fields(ReplayConfig)
        if getattr(baseline.config, field.name) != getattr(candidate.config, field.name)
    )
    return ReplayDiff(
        template_delta=candidate.template_count - baseline.template_count,
        prefix_duplicate_delta=candidate.prefix_duplicate_count - baseline.prefix_duplicate_count,
        config_mismatch=mismatch,
    )


def _measure_with(samples: list[LogSample], overrides: dict[str, str]) -> ReplayReport:
    previous = {name: os.environ.get(name) for name in overrides}
    os.environ.update(overrides)
    try:
        return measure(samples)
    finally:
        for name, value in previous.items():
            if value is None:
                del os.environ[name]
            else:
                os.environ[name] = value


def _parse_overrides(pairs: list[str]) -> dict[str, str]:
    overrides = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if key not in _TUNING:
            raise SystemExit(f"unknown config key {key!r}, expected one of {', '.join(_TUNING)}")
        overrides[_TUNING[key].env_var] = value
    return overrides


def _format_report(label: str, report: ReplayReport) -> str:
    config = " ".join(f"{field.name}={getattr(report.config, field.name)}" for field in fields(ReplayConfig))
    lines = [
        f"{label}: {report.template_count} templates, "
        f"{report.prefix_duplicate_count} prefix-duplicates, "
        f"from {report.sample_count} bodies",
        f"  config: {config}",
    ]
    lines.extend(
        f"    {service.service_name}: {service.template_count} templates, "
        f"{service.prefix_duplicate_count} prefix-duplicates, from {service.sample_count} bodies"
        for service in report.services
    )
    return "\n".join(lines)


def _format_diff(diff: ReplayDiff) -> str:
    lines = [
        f"diff: {diff.template_delta:+d} templates, {diff.prefix_duplicate_delta:+d} prefix-duplicates",
    ]
    if diff.config_mismatch:
        lines.append(
            f"  WARNING: {', '.join(diff.config_mismatch)} differ between the runs, "
            "so these deltas do not isolate the code change"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("corpus", type=Path, help="JSONL file of log rows")
    parser.add_argument(
        "--compare",
        metavar="KEY=VALUE",
        action="append",
        default=[],
        help="mine a second time with these tuning overrides and diff the two",
    )
    parser.add_argument("--save", type=Path, help="write this run's report for a later --baseline")
    parser.add_argument("--baseline", type=Path, help="diff this run against a saved report")
    args = parser.parse_args(argv)

    samples = load_corpus(args.corpus)
    report = measure(samples)
    print(_format_report("current", report))

    if args.compare:
        candidate = _measure_with(samples, _parse_overrides(args.compare))
        print(_format_report("compared", candidate))
        print(_format_diff(diff_reports(report, candidate)))

    if args.baseline:
        saved = json.loads(args.baseline.read_text())
        baseline = ReplayReport(
            **{
                **saved,
                "config": ReplayConfig(**saved["config"]),
                "services": tuple(ServiceReport(**service) for service in saved.get("services", ())),
            }
        )
        print(_format_report("baseline", baseline))
        print(_format_diff(diff_reports(baseline, report)))

    if args.save:
        args.save.write_text(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    main()
