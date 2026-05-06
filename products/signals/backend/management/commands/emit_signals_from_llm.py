import json
import random
import asyncio
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team
from posthog.temporal.data_imports.signals import get_signal_config
from posthog.temporal.data_imports.signals.pipeline import run_signal_pipeline

from products.signals.backend.models import SignalSourceConfig
from products.signals.eval.llm_gen import SOURCE_KINDS, WRAPPERS, generate_canonical_signals
from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.prompts import SYSTEM_PROMPT, VARIATION_CHOICES, build_user_prompt


class Command(BaseCommand):
    help = (
        "Generate synthetic signals via an LLM and emit them through the real signals pipeline.\n\n"
        "Sibling to emit_signals_from_fixture, but instead of reading static JSON, asks an LLM "
        "to produce realistic signal content steered by --theme / --clusters / --variation flags. "
        "The LLM produces a source-agnostic {title, body} per signal; per-source wrappers stub the "
        "raw fixture fields each parser expects (github_issue_emitter, linear_issue_emitter, "
        "zendesk_ticket_emitter, conversations_ticket_emitter), so existing emitters are reused unchanged.\n\n"
        "Examples:\n"
        "  # Single cluster — 3 paraphrased github issues about a single theme\n"
        "  python manage.py emit_signals_from_llm --team-id 1 --type github --theme 'insights datepicker custom ranges' --count 3\n\n"
        "  # Multi-cluster — separate themes, mixed counts/variation\n"
        "  python manage.py emit_signals_from_llm --team-id 1 --type linear \\\n"
        "    --clusters 'datepicker:3:paraphrase,workflow metrics:2:variant,funnels:1:dup'\n\n"
        "  # Cross-source mix — one logical batch split across sources\n"
        "  python manage.py emit_signals_from_llm --team-id 1 --theme 'rate limiting bug' --count 6 \\\n"
        "    --mix 'github:3,linear:1,zendesk:2'\n\n"
        "  # Cost / debug knobs\n"
        "  python manage.py emit_signals_from_llm --team-id 1 --type github --theme X --count 2 --print-prompt\n"
        "  python manage.py emit_signals_from_llm --team-id 1 --type github --theme X --count 2 --dry-run\n"
        "  python manage.py emit_signals_from_llm --team-id 1 --type github --theme X --count 2 --save-fixture out.json\n"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to emit signals for",
        )
        # --type vs --mix: --type is a single source, --mix splits one logical batch across sources.
        parser.add_argument(
            "--type",
            choices=sorted(SOURCE_KINDS),
            default=None,
            help=f"Single source to emit as. One of {sorted(SOURCE_KINDS)}. Mutually exclusive with --mix.",
        )
        parser.add_argument(
            "--mix",
            type=str,
            default=None,
            help=(
                "Cross-source mix recipe: 'github:3,linear:1,zendesk:2'. "
                "Total must equal --count (single-theme mode) or sum of cluster counts (--clusters mode). "
                "Mutually exclusive with --type."
            ),
        )
        # --theme vs --clusters: --theme is one cluster, --clusters is a recipe of multiple clusters.
        parser.add_argument(
            "--theme",
            type=str,
            default=None,
            help=(
                "Subject of the signals (e.g. 'insights datepicker custom ranges'). "
                "Used with --count and --variation. Mutually exclusive with --clusters."
            ),
        )
        parser.add_argument(
            "--count",
            type=int,
            default=3,
            help="Number of signals when using --theme (default 3, ignored when using --clusters).",
        )
        parser.add_argument(
            "--variation",
            choices=list(VARIATION_CHOICES),
            default="paraphrase",
            help=(
                "How similar the generated signals should be (default paraphrase). "
                "dup=near-identical, paraphrase=same root issue different wording, "
                "variant=same area different sub-problem, tangent=topic-adjacent but distinct. "
                "Ignored when using --clusters (variation is per-cluster there)."
            ),
        )
        parser.add_argument(
            "--clusters",
            type=str,
            default=None,
            help=(
                "Cluster recipe: 'theme1:count1[:variation1],theme2:count2[:variation2],...'. "
                "Variation defaults to 'paraphrase' when omitted. "
                "Each cluster runs its own LLM call. Mutually exclusive with --theme/--count/--variation."
            ),
        )
        parser.add_argument(
            "--steering",
            type=str,
            default=None,
            help="Free-form extra prompt steering appended to the user prompt (e.g. 'all from frustrated enterprise users on safari').",
        )
        parser.add_argument(
            "--temperature",
            type=float,
            default=0.7,
            help="LLM sampling temperature (default 0.7). Lower = more consistent, higher = more varied.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Seed used to derive deterministic stub IDs / URLs in the wrappers (default 42). Does NOT affect LLM sampling.",
        )
        parser.add_argument(
            "--save-fixture",
            type=str,
            default=None,
            help="Optional path to write the wrapped records as JSON before emitting (for replay or inspection).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Generate + wrap signals but DO NOT emit them through the pipeline. Implies --print-prompt.",
        )
        parser.add_argument(
            "--print-prompt",
            action="store_true",
            help="Print the system + user prompts that would be sent to the LLM, then continue.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        clusters = self._parse_clusters(options)
        target_total = sum(c["count"] for c in clusters)
        source_assignments = self._parse_mix(options, target_total=target_total)

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        rng = random.Random(options["seed"])
        all_canonical: list[CanonicalSignal] = []
        for ci, cluster in enumerate(clusters):
            user_prompt = build_user_prompt(
                theme=cluster["theme"],
                count=cluster["count"],
                variation=cluster["variation"],
                extra_steering=options.get("steering"),
            )
            if options["print_prompt"] or options["dry_run"]:
                self.stdout.write(f"\n--- cluster {ci} prompt (theme={cluster['theme']!r}) ---")
                self.stdout.write(f"[system]\n{SYSTEM_PROMPT}\n")
                self.stdout.write(f"[user]\n{user_prompt}\n")
            if options["dry_run"]:
                continue
            self.stdout.write(
                f"Generating cluster {ci + 1}/{len(clusters)}: theme={cluster['theme']!r} "
                f"count={cluster['count']} variation={cluster['variation']}..."
            )
            cluster_signals = asyncio.run(
                generate_canonical_signals(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=options["temperature"],
                )
            )
            if len(cluster_signals) != cluster["count"]:
                self.stderr.write(
                    self.style.WARNING(
                        f"Cluster {ci}: requested {cluster['count']}, LLM returned {len(cluster_signals)} — using as-is"
                    )
                )
            all_canonical.extend(cluster_signals)

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run complete — no LLM calls or pipeline emits performed."))
            return

        # `emit_signal()` silently drops records when a `SignalSourceConfig` row
        # for the (team, source_product, source_type) doesn't exist with enabled=True.
        # In DEBUG-only dev usage we'd rather auto-enable than silently drop.
        # Gated behind the dry-run early return so dry runs are side-effect free.
        self._ensure_source_configs_enabled(team, source_assignments)

        # Wrapping: pair each canonical signal with a source kind from source_assignments.
        # If --mix was provided, source_assignments has exactly len(all_canonical) entries.
        # If --type was provided, all entries are the same source.
        if len(source_assignments) != len(all_canonical):
            # Re-balance to actual produced count (LLM may have produced fewer/more than requested).
            source_assignments = self._rebalance_assignments(source_assignments, len(all_canonical), rng)

        records_by_source: dict[str, list[dict]] = {kind: [] for kind in WRAPPERS}
        for idx, (signal, source_kind) in enumerate(zip(all_canonical, source_assignments)):
            _, _, wrapper_fn = WRAPPERS[source_kind]
            records_by_source[source_kind].append(wrapper_fn(signal, idx, options["seed"]))

        if options["save_fixture"]:
            out_path = Path(options["save_fixture"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w") as f:
                json.dump(
                    {
                        "canonical": [s.model_dump() for s in all_canonical],
                        "wrapped": {k: v for k, v in records_by_source.items() if v},
                        "source_assignments": source_assignments,
                    },
                    f,
                    indent=2,
                )
            self.stdout.write(f"Saved fixture to {out_path}")

        # Emit per-source through run_signal_pipeline (one call per source kind that has records).
        emit_summary: dict[str, int] = {}
        for source_kind, records in records_by_source.items():
            if not records:
                continue
            registry_source, registry_schema, _ = WRAPPERS[source_kind]
            config = get_signal_config(registry_source, registry_schema)
            if config is None:
                raise CommandError(f"No signal config registered for {registry_source}/{registry_schema}")
            self.stdout.write(f"Emitting {len(records)} {source_kind} records through run_signal_pipeline...")
            result = asyncio.run(
                run_signal_pipeline(
                    team=team,
                    config=config,
                    records=records,
                    extra={"command": "emit_signals_from_llm", "source": source_kind},
                )
            )
            emit_summary[source_kind] = (
                result.get("signals_emitted", len(records)) if isinstance(result, dict) else len(records)
            )

        self.stdout.write(self.style.SUCCESS(f"Pipeline finished: {emit_summary}"))

    def _ensure_source_configs_enabled(self, team: Team, source_assignments: list[str]) -> None:
        """Make sure each source_kind we plan to emit has an enabled SignalSourceConfig.

        Without this, emit_signal() in products/signals/backend/api.py silently returns,
        and the records vanish from the pipeline with no error.
        """
        needed_kinds = sorted(set(source_assignments))
        for kind in needed_kinds:
            registry_source, registry_schema, _ = WRAPPERS[kind]
            # WRAPPERS uses the registry's source_type names ('Github', 'Linear', 'Zendesk', 'conversations'),
            # but SignalSourceConfig stores the lowercase product name (the SignalEmitterOutput.source_product).
            source_product = registry_source.lower()
            source_type = "issue" if registry_schema == "issues" else "ticket"
            existing = SignalSourceConfig.objects.filter(
                team=team, source_product=source_product, source_type=source_type
            ).first()
            was_disabled = existing is not None and not existing.enabled
            _, created = SignalSourceConfig.objects.update_or_create(
                team=team,
                source_product=source_product,
                source_type=source_type,
                defaults={"enabled": True},
            )
            if created:
                self.stdout.write(
                    self.style.WARNING(
                        f"Auto-enabled SignalSourceConfig for {source_product}/{source_type} on team {team.id} "
                        f"(was missing — emit_signal would have silently dropped these records)"
                    )
                )
            elif was_disabled:
                self.stdout.write(
                    self.style.WARNING(
                        f"Re-enabled previously-disabled SignalSourceConfig for {source_product}/{source_type} "
                        f"on team {team.id} (was enabled=False — emit_signal would have silently dropped these records)"
                    )
                )

    # ---- arg parsing helpers ------------------------------------------------

    def _parse_clusters(self, options: dict) -> list[dict]:
        """Returns a list of {theme, count, variation} dicts.

        --theme / --count / --variation produce a single cluster.
        --clusters produces multiple. They are mutually exclusive.
        """
        if options["clusters"] and options["theme"]:
            raise CommandError("--clusters and --theme are mutually exclusive")
        if not options["clusters"] and not options["theme"]:
            raise CommandError("Provide either --theme or --clusters")
        if options["clusters"]:
            return [self._parse_one_cluster(spec) for spec in options["clusters"].split(",")]
        count = options["count"]
        if count < 1 or count > 20:
            raise CommandError(f"--count must be between 1 and 20, got {count}")
        theme = options["theme"].strip()
        if not theme:
            raise CommandError("--theme must not be empty")
        return [
            {
                "theme": theme,
                "count": count,
                "variation": options["variation"],
            }
        ]

    def _parse_one_cluster(self, spec: str) -> dict:
        spec = spec.strip()
        # rsplit so themes can contain colons (e.g. "TypeError: foo:3:paraphrase").
        parts = spec.rsplit(":", maxsplit=2)
        if len(parts) not in (2, 3):
            raise CommandError(f"Invalid cluster spec {spec!r}. Expected 'theme:count' or 'theme:count:variation'.")
        theme = parts[0].strip()
        try:
            count = int(parts[1])
        except ValueError:
            raise CommandError(f"Invalid count in cluster spec {spec!r}: {parts[1]!r} is not an integer")
        if count < 1 or count > 20:
            raise CommandError(f"Cluster count must be between 1 and 20, got {count} in {spec!r}")
        variation = parts[2].strip() if len(parts) == 3 else "paraphrase"
        if variation not in VARIATION_CHOICES:
            raise CommandError(
                f"Invalid variation {variation!r} in cluster spec {spec!r}. Must be one of {list(VARIATION_CHOICES)}"
            )
        if not theme:
            raise CommandError(f"Empty theme in cluster spec {spec!r}")
        return {"theme": theme, "count": count, "variation": variation}

    def _parse_mix(self, options: dict, *, target_total: int) -> list[str]:
        """Returns a list of source-kind assignments, one per signal slot.

        --type X means all slots are X. --mix 'a:n,b:m' splits proportionally.
        """
        if options["type"] and options["mix"]:
            raise CommandError("--type and --mix are mutually exclusive")
        if not options["type"] and not options["mix"]:
            raise CommandError("Provide either --type or --mix")
        if options["type"]:
            return [options["type"]] * target_total

        # Parse --mix
        assignments: list[str] = []
        parts = [p.strip() for p in options["mix"].split(",")]
        for part in parts:
            kv = part.split(":")
            if len(kv) != 2:
                raise CommandError(f"Invalid mix entry {part!r}. Expected 'source:count'.")
            kind = kv[0].strip()
            if kind not in SOURCE_KINDS:
                raise CommandError(f"Unknown source kind {kind!r} in --mix. Must be one of {sorted(SOURCE_KINDS)}.")
            try:
                n = int(kv[1])
            except ValueError:
                raise CommandError(f"Invalid count in mix entry {part!r}: {kv[1]!r} is not an integer")
            if n < 0:
                raise CommandError(f"Mix count must be non-negative, got {n} in {part!r}")
            assignments.extend([kind] * n)
        if len(assignments) != target_total:
            raise CommandError(
                f"--mix totals {len(assignments)} but --count / --clusters totals {target_total}; they must match"
            )
        return assignments

    def _rebalance_assignments(self, assignments: list[str], actual: int, rng: random.Random) -> list[str]:
        """If LLM returned a different count than requested, keep proportions but match actual length."""
        if not assignments:
            return ["github"] * actual
        if len(assignments) == actual:
            return assignments
        counts = Counter(assignments)
        total = sum(counts.values())
        # Re-scale proportionally.
        rebalanced: list[str] = []
        for kind, n in counts.items():
            new_n = max(1, round(n * actual / total)) if n > 0 else 0
            rebalanced.extend([kind] * new_n)
        # Trim or extend to exactly `actual`.
        while len(rebalanced) > actual:
            rebalanced.pop(rng.randrange(len(rebalanced)))
        while len(rebalanced) < actual:
            rebalanced.append(rng.choice(list(counts.keys())))
        return rebalanced
