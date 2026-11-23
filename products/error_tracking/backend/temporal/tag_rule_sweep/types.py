from datetime import datetime

from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.issue_tags.sweep import TagRuleSweepSkipReason


@frozen
class TagRuleSweepInputs:
    # True makes every team a dry run, for a manual run. Otherwise RULE_SWEEP_WRITES_FLAG decides for each team.
    force_dry_run: bool = False
    # Each team runs one query on the offline cluster, which shares its concurrent query limit with every product.
    max_concurrent_teams: int = 4


@frozen
class SweepTeamTagRulesInputs:
    team_id: int
    start: datetime
    end: datetime
    force_dry_run: bool


@frozen
class SweepTeamTagRulesResult:
    skipped: TagRuleSweepSkipReason | None = None
    dry_run: bool = True
    rules_run: int = 0
    rules_skipped: int = 0
    matching_issues: int = 0
    labels_to_write: int = 0
    labels_written: int = 0
    truncated: bool = False


@frozen
class TagRuleSweepResult:
    teams: int
    teams_skipped: int
    teams_failed: int
    rules_run: int
    rules_skipped: int
    matching_issues: int
    labels_to_write: int
    labels_written: int
