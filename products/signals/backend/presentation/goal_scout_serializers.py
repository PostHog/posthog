from typing import Any

from django.db import models

from rest_framework import serializers

REPOSITORY_PATTERN = r"^[\w.-]+/[\w.-]+$"


class GoalScoutDirection(models.TextChoices):
    INCREASE = "increase", "Higher is better"
    DECREASE = "decrease", "Lower is better"


class GoalScoutWorkKind(models.TextChoices):
    TRACKING = "tracking", "Tracking check"
    IDEA = "idea", "Idea to test"


class GoalScoutStatus(models.TextChoices):
    SETTING_UP = "setting_up", "Setting up"
    RUNNING = "running", "Running"
    PAUSED = "paused", "Paused"
    REACHED = "reached", "Goal reached"
    SPENT = "spent", "Budget used"
    CLOSED = "closed", "Closed"


class GoalScoutWorkStage(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    DISMISSED = "dismissed", "Dismissed"
    BUILDING = "building", "Building"
    REVIEW = "review", "In review"
    LIVE = "live", "Live"
    DONE = "done", "Done"
    DROPPED = "dropped", "Dropped"
    STUCK = "stuck", "Stuck"


class GoalScoutIdeaSource(models.TextChoices):
    SCOUT = "scout", "Scout"
    OWNER = "owner", "Owner"


class GoalScoutIdeaAssessment(models.TextChoices):
    NONE = "", "None"
    PENDING = "pending", "Pending"
    SUPPORTED = "supported", "Supported"
    NOT_SUPPORTED = "not_supported", "Not supported"


class GoalScoutIdeaOutcome(models.TextChoices):
    NONE = "", "No outcome yet"
    WON = "won", "The idea won"
    LOST = "lost", "The idea lost"
    FLAT = "flat", "No clear effect"
    HARMED = "harmed", "A guardrail got worse"
    BROKEN = "broken", "The test was broken"
    DROPPED = "dropped", "The idea was dropped"


class GoalScoutEvidenceKind(models.TextChoices):
    REPLAY = "replay", "Session replay"
    INSIGHT = "insight", "Insight"
    CHART = "chart", "Chart"
    EXPERIMENT = "experiment", "Experiment"
    ERROR = "error", "Error"
    LINK = "link", "Link"


class GoalScoutTile(models.TextChoices):
    TRACKING = "tracking", "Tracking"
    MEASURE = "measure", "Measure"
    SCOUT = "scout", "Scout"
    IDEA = "idea", "Idea"
    EXPERIMENT = "experiment", "Experiment"
    PULL_REQUEST = "pull_request", "Pull request"
    PROBLEM = "problem", "Problem"
    IDLE = "idle", "Idle"
    PAUSED = "paused", "Paused"
    REACHED = "reached", "Reached"
    ENDED = "ended", "Ended"


class GoalScoutActionKind(models.TextChoices):
    IDEAS = "ideas", "Ideas"
    EDIT = "edit", "Edit"
    PULL_REQUEST = "pull_request", "Pull request"
    WORK = "work", "Work"
    BUDGET = "budget", "Budget"
    SETTINGS = "settings", "Settings"


class GoalScoutWorkAction(models.TextChoices):
    RETRY = "retry", "Retry"
    RETRY_CLEANUP = "retry_cleanup", "Retry flag cleanup"
    DROP = "drop", "Drop"


class GoalScoutMeasureSource(models.TextChoices):
    EXISTING = "existing", "Existing insight"
    NEW = "new", "New measure"


class GoalScoutActivityResource(models.TextChoices):
    NONE = "", "None"
    TASK = "task", "Task"
    EXPERIMENT = "experiment", "Experiment"
    FLAG = "flag", "Feature flag"
    PULL_REQUEST = "pull_request", "Pull request"


class GoalScoutGuardrailSerializer(serializers.Serializer):
    insight = serializers.CharField(max_length=32, help_text="Short ID of the saved insight used as a guardrail.")
    name = serializers.CharField(max_length=255, help_text="Name of the guardrail metric.")
    direction = serializers.ChoiceField(
        choices=GoalScoutDirection.choices,
        default=GoalScoutDirection.INCREASE,
        help_text="Whether higher or lower is better.",
    )
    max_regression = serializers.FloatField(
        min_value=0, max_value=1, default=0.05, help_text="Largest tolerated relative regression, 0.05 for 5%."
    )


class GoalScoutWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, help_text="Short name of the goal scout.")
    statement = serializers.CharField(max_length=10000, help_text="What you believe will improve and why.")
    area = serializers.CharField(
        max_length=50, allow_blank=True, default="", help_text="Product area, stored as a scout tag."
    )
    repositories = serializers.ListField(
        child=serializers.RegexField(REPOSITORY_PATTERN, max_length=255),
        max_length=10,
        required=False,
        help_text="GitHub repositories in owner/repository form. The first is where pull requests open.",
    )
    goal_insight = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        help_text="Saved insight with one series that measures the goal. Leave empty and describe the measure instead.",
    )
    goal_description = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        help_text="The measure in words when no saved insight fits. The tracking task finds or creates the insight.",
    )
    goal_metric = serializers.CharField(max_length=255, help_text="Name of the primary metric.")
    ideas = serializers.ListField(
        child=serializers.CharField(max_length=255),
        max_length=5,
        required=False,
        default=list,
        help_text="The owner's own ideas. The scout checks each one against the data.",
    )
    secondary_metrics = GoalScoutGuardrailSerializer(
        many=True, required=False, help_text="Guardrails that must not get worse."
    )
    target = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        required=False,
        allow_null=True,
        help_text="Target value of the primary metric. Set it after the tracking task finds the insight of a described measure.",
    )
    direction = serializers.ChoiceField(
        choices=GoalScoutDirection.choices,
        required=False,
        help_text="Whether higher or lower is better.",
    )
    unit = serializers.CharField(max_length=32, allow_blank=True, required=False, help_text="Display unit, such as %.")
    budget_cents = serializers.IntegerField(
        min_value=0, max_value=1000000000, help_text="Budget for this goal in USD cents."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if len(attrs.get("secondary_metrics") or []) > 5:
            raise serializers.ValidationError({"secondary_metrics": "Choose up to five guardrails."})
        if "repositories" in attrs:
            attrs["repositories"] = list(dict.fromkeys(attrs["repositories"]))
        if ("repositories" in attrs or not self.partial) and not attrs.get("repositories"):
            raise serializers.ValidationError({"repositories": "Choose at least one repository."})
        if not self.partial:
            if not attrs.get("goal_insight") and not attrs.get("goal_description", "").strip():
                raise serializers.ValidationError(
                    {"goal_insight": "Choose a saved insight, or describe how to measure the goal."}
                )
            if attrs.get("goal_insight") and attrs.get("target") is None:
                raise serializers.ValidationError({"target": "Set the value to reach."})
        return attrs


class GoalScoutMetricSerializer(serializers.Serializer):
    unit = serializers.CharField(allow_blank=True, help_text="Display unit from the saved insight.")
    values = serializers.ListField(child=serializers.FloatField(), help_text="Values in chronological order.")
    dates = serializers.ListField(child=serializers.CharField(), help_text="Dates of the values.")
    current = serializers.FloatField(allow_null=True, help_text="Latest complete value.")
    message = serializers.CharField(allow_blank=True, help_text="Why a measurement is unavailable.")


class GoalScoutMoneySerializer(serializers.Serializer):
    allocated_cents = serializers.IntegerField(help_text="Budget of the goal in USD cents.")
    spent_cents = serializers.IntegerField(help_text="Recorded spend of the goal's runs and tasks in USD cents.")
    available_cents = serializers.IntegerField(help_text="Budget left in USD cents.")


class GoalScoutEvidenceSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=GoalScoutEvidenceKind.choices, help_text="What the evidence link points to.")
    label = serializers.CharField(help_text="Short text that describes the evidence.")  # type: ignore[assignment]
    url = serializers.CharField(help_text="Link to the PostHog data, or chart:<id> for a chart in the report.")


class GoalScoutPlanSerializer(serializers.Serializer):
    days = serializers.IntegerField(allow_null=True, help_text="Days the experiment runs before the verdict.")
    mde = serializers.FloatField(allow_null=True, help_text="Smallest relative change, in percent, the test can find.")
    audience = serializers.IntegerField(allow_null=True, help_text="People a day who see the change.")


class GoalScoutPlanAnchorSerializer(serializers.Serializer):
    mde = serializers.FloatField(help_text="Smallest relative change, in percent, that sample_size detects.")
    sample_size = serializers.IntegerField(help_text="Total people across both variants to detect mde.")


class GoalScoutPlanInputSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=2, max_value=365, help_text="Days the experiment runs.")
    mde = serializers.FloatField(min_value=0.1, max_value=100, help_text="Smallest change worth finding, in percent.")
    audience = serializers.IntegerField(min_value=1, help_text="People a day who see the change.")


class GoalScoutIdeaResultSerializer(serializers.Serializer):
    variant = serializers.CharField(required=False, help_text="Variant kept when the experiment ended.")
    verdict = serializers.CharField(required=False, help_text="Why the experiment ended this way.")
    exposures = serializers.DictField(
        child=serializers.IntegerField(), required=False, help_text="People exposed per variant."
    )
    primary = serializers.DictField(
        child=serializers.ListField(child=serializers.FloatField(allow_null=True), allow_null=True),
        required=False,
        help_text="Relative effect interval on the primary metric per test variant.",
    )
    harmed_guardrails = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Guardrails that got worse."
    )


class GoalScoutCleanupSerializer(serializers.Serializer):
    task_id = serializers.CharField(help_text="Task that removes the experiment's flag from the code.")
    task_status = serializers.CharField(help_text="Status of the cleanup task's latest run.")
    pr_url = serializers.CharField(allow_blank=True, help_text="Pull request of the cleanup task.")
    pr_state = serializers.CharField(allow_blank=True, help_text="State of the cleanup pull request.")


class GoalScoutWorkSerializer(serializers.Serializer):
    id = serializers.CharField(
        help_text="Work ID: the idea row for tracking and built ideas, the report for proposed ideas, or owner-<n> for an owner idea the scout has not checked yet."
    )
    kind = serializers.ChoiceField(choices=GoalScoutWorkKind.choices, help_text="Tracking check or idea.")
    stage = serializers.ChoiceField(
        choices=GoalScoutWorkStage.choices, help_text="Where this work is in its lifecycle."
    )
    title = serializers.CharField(help_text="Work title.")
    summary = serializers.CharField(allow_blank=True, help_text="The report text behind the work.")
    note = serializers.CharField(allow_blank=True, help_text="Latest status in plain language.")
    pr_url = serializers.CharField(allow_blank=True, help_text="Pull request of the work's task.")
    experiment_id = serializers.IntegerField(allow_null=True, help_text="Experiment that measures the idea.")
    outcome = serializers.ChoiceField(choices=GoalScoutIdeaOutcome.choices, help_text="How a built idea ended.")
    result = GoalScoutIdeaResultSerializer(help_text="Measured facts: exposures, primary intervals, verdict.")
    task_id = serializers.CharField(allow_null=True, help_text="Implementation task doing the work.")
    task_status = serializers.CharField(help_text="Status of the task's latest run.")
    spent_cents = serializers.IntegerField(help_text="Recorded spend of this work in USD cents.")
    created_at = serializers.DateTimeField(help_text="When the work or report was created.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When the work finished.")
    number = serializers.IntegerField(allow_null=True, help_text="Build number of the idea within the goal.")
    chosen_at = serializers.DateTimeField(allow_null=True, help_text="When someone chose to build the idea.")
    merged_at = serializers.DateTimeField(allow_null=True, help_text="When the pull request merged.")
    exposed_at = serializers.DateTimeField(allow_null=True, help_text="When the first people saw the change.")
    source = serializers.ChoiceField(choices=GoalScoutIdeaSource.choices, help_text="Who proposed the idea.")  # type: ignore[assignment]
    assessment = serializers.ChoiceField(
        choices=GoalScoutIdeaAssessment.choices,
        allow_blank=True,
        help_text="The scout's check of the idea against the data.",
    )
    evidence = GoalScoutEvidenceSerializer(many=True, help_text="Links to the PostHog data behind the idea.")
    report_id = serializers.CharField(allow_null=True, help_text="Report that describes the work.")
    dismissed_reason = serializers.CharField(allow_blank=True, help_text="Why someone dismissed the idea.")
    moves_metric = serializers.CharField(allow_blank=True, help_text="The metric the scout expects this idea to move.")
    plan = GoalScoutPlanSerializer(help_text="Experiment plan for an idea.")
    cleanup = GoalScoutCleanupSerializer(allow_null=True, help_text="Flag cleanup task after the experiment ended.")


class GoalScoutStateActionSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Button text.")  # type: ignore[assignment]
    kind = serializers.ChoiceField(choices=GoalScoutActionKind.choices, help_text="What the button opens or does.")
    work_id = serializers.CharField(allow_null=True, help_text="Work the button opens or acts on.")
    work_action = serializers.ChoiceField(
        choices=GoalScoutWorkAction.choices, allow_null=True, help_text="Action the button runs on the work, or empty."
    )
    url = serializers.CharField(allow_blank=True, help_text="Pull request to open.")


class GoalScoutStateSerializer(serializers.Serializer):
    tile = serializers.ChoiceField(
        choices=GoalScoutTile.choices, help_text="Which part of the loop the status is about."
    )
    headline = serializers.CharField(help_text="Main status line.")
    detail = serializers.CharField(allow_blank=True, help_text="Second status line.")
    working = serializers.BooleanField(help_text="Whether the goal works on this step now.")
    action = GoalScoutStateActionSerializer(allow_null=True, help_text="The owner's next step.")
    scout_reason = serializers.CharField(help_text="What the scout does now and why.")
    ready_ideas = serializers.IntegerField(help_text="Ideas ready for the owner to choose.")
    build_blocked = serializers.CharField(allow_blank=True, help_text="Why no idea can be built now, or empty.")
    can_add_idea = serializers.BooleanField(help_text="Whether the goal takes new owner ideas.")
    needs_you = serializers.BooleanField(help_text="Whether the goal waits for the owner.")


class GoalScoutEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Goal ID, the same as the scout config ID.")
    skill_name = serializers.CharField(help_text="Scout name, used in the scout page URL.")
    title = serializers.CharField(help_text="Goal name.")
    statement = serializers.CharField(help_text="What we believe and why.")
    area = serializers.CharField(allow_blank=True, help_text="Product area.")
    repositories = serializers.ListField(
        child=serializers.CharField(), help_text="Connected repositories. The first is where pull requests open."
    )
    goal_insight = serializers.CharField(allow_blank=True, help_text="Primary metric insight.")
    goal_description = serializers.CharField(allow_blank=True, help_text="The measure in words, when described.")
    goal_metric = serializers.CharField(help_text="Primary metric name.")
    secondary_metrics = GoalScoutGuardrailSerializer(many=True, help_text="Guardrails.")
    target = serializers.DecimalField(
        max_digits=20, decimal_places=4, allow_null=True, help_text="Primary metric target, empty until set."
    )
    direction = serializers.ChoiceField(
        choices=GoalScoutDirection.choices, help_text="Whether higher or lower is better."
    )
    unit = serializers.CharField(allow_blank=True, help_text="Primary metric unit.")
    status = serializers.ChoiceField(choices=GoalScoutStatus.choices, help_text="Goal lifecycle state.")
    baseline_value = serializers.FloatField(allow_null=True, help_text="Primary metric when the goal started running.")
    baseline_at = serializers.DateTimeField(allow_null=True, help_text="When the baseline was recorded.")
    owner_name = serializers.CharField(help_text="Name of the person who created the goal.")
    money = GoalScoutMoneySerializer(help_text="Budget and real spend.")
    metric = GoalScoutMetricSerializer(help_text="Primary metric history.")
    ideas_tried = serializers.IntegerField(help_text="Ideas measured to a conclusion.")
    ideas_won = serializers.IntegerField(help_text="Ideas that improved the primary metric.")
    state = GoalScoutStateSerializer(help_text="What the goal does now and what it needs from the owner.")


class GoalScoutSpendSerializer(serializers.Serializer):
    scout_cents = serializers.IntegerField(help_text="Spend on finding ideas, in USD cents.")
    scout_runs = serializers.IntegerField(help_text="Scout runs that recorded spend.")
    ideas_cents = serializers.IntegerField(help_text="Spend on building ideas, in USD cents.")
    tracking_cents = serializers.IntegerField(help_text="Spend on the tracking check, in USD cents.")
    returned_cents = serializers.IntegerField(help_text="Budget left unused when the goal ended, in USD cents.")
    tested_ideas = serializers.IntegerField(help_text="Ideas that got a test result.")
    per_tested_idea_cents = serializers.IntegerField(
        allow_null=True, help_text="Total spend divided by tested ideas. Empty with no tests."
    )


class GoalScoutSpendPointSerializer(serializers.Serializer):
    at = serializers.DateTimeField(help_text="When the spend was recorded.")
    spent_cents = serializers.IntegerField(help_text="Total spend up to this time, in USD cents.")


class GoalScoutResultsSerializer(serializers.Serializer):
    started_at = serializers.DateTimeField(help_text="When the goal started measuring.")
    ended_at = serializers.DateTimeField(allow_null=True, help_text="When the goal ended.")
    met_at_start = serializers.BooleanField(help_text="Whether the goal met the target before any idea shipped.")
    spend = GoalScoutSpendSerializer(help_text="Where the budget went.")


class GoalScoutDetailSerializer(GoalScoutEntrySerializer):
    results = GoalScoutResultsSerializer(allow_null=True, help_text="Results summary, empty until the goal ends.")
    work = GoalScoutWorkSerializer(many=True, help_text="Tracking checks and ideas, newest first.")
    spend_history = GoalScoutSpendPointSerializer(many=True, help_text="Cumulative spend over time.")
    is_owner = serializers.BooleanField(help_text="Whether the viewer created this goal.")
    secondary_values = GoalScoutMetricSerializer(many=True, help_text="Current guardrail readings.")
    scout_running = serializers.BooleanField(help_text="Whether a scout run is in progress.")
    plan_anchor = GoalScoutPlanAnchorSerializer(
        allow_null=True, help_text="One experiment estimate to rescale for any smallest change and audience."
    )


class GoalScoutActivitySerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable activity entry identifier.")
    at = serializers.DateTimeField(help_text="When the event happened.")
    title = serializers.CharField(help_text="Summary of the event.")
    detail = serializers.CharField(allow_blank=True, help_text="Related work, changed fields or amount.")
    resource = serializers.ChoiceField(choices=GoalScoutActivityResource.choices, help_text="Linked resource to open.")
    resource_id = serializers.CharField(allow_blank=True, help_text="Identifier or URL of the linked resource.")


class GoalScoutIdeaSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, help_text="The owner's idea, in one sentence.")


class GoalScoutBuildSerializer(serializers.Serializer):
    work_id = serializers.CharField(max_length=64, help_text="Work ID of the proposed idea to build.")
    plan = GoalScoutPlanInputSerializer(
        required=False,
        allow_null=True,
        help_text="The experiment plan the owner approves with the build. Without one, the test is planned from its traffic once it is live.",
    )


class GoalScoutActSerializer(serializers.Serializer):
    work_id = serializers.CharField(
        max_length=64,
        help_text="Work ID of tracking or a built idea, or owner-<n> for an owner idea the scout has not checked yet.",
    )
    action = serializers.ChoiceField(
        choices=GoalScoutWorkAction.choices,
        help_text="Retry stuck work, retry a failed flag cleanup, or drop an idea in progress or an owner idea that waits for the scout.",
    )


class GoalScoutMetricPreviewQuerySerializer(serializers.Serializer):
    insight = serializers.CharField(max_length=32, help_text="Short ID of the saved insight to preview.")


class GoalScoutMeasureRequestSerializer(serializers.Serializer):
    goal = serializers.CharField(max_length=500, help_text="What the owner wants to change, in their own words.")


class GoalScoutMeasureOptionSerializer(serializers.Serializer):
    insight = serializers.CharField(help_text="Short ID of the insight that measures this option.")
    name = serializers.CharField(help_text="Name of the measure.")
    source = serializers.ChoiceField(
        choices=GoalScoutMeasureSource.choices, help_text="A saved insight, or a new measure."
    )  # type: ignore[assignment]
    definition = serializers.CharField(help_text="What the measure counts.")
    current = serializers.FloatField(allow_null=True, help_text="The latest complete value.")
    unit = serializers.CharField(allow_blank=True, help_text="Unit of the value, such as %.")
    test_days = serializers.IntegerField(allow_null=True, help_text="Planned days for one experiment on it.")
    values = serializers.ListField(child=serializers.FloatField(), help_text="Recent values, oldest first.")
    dates = serializers.ListField(child=serializers.CharField(), help_text="Dates of the recent values.")


class GoalScoutMeasureSearchSerializer(serializers.Serializer):
    options = GoalScoutMeasureOptionSerializer(many=True, help_text="Measures that fit the goal, best first.")
    draft = serializers.CharField(allow_blank=True, help_text="One sentence that defines the best measure.")


class GoalScoutLabelsRequestSerializer(serializers.Serializer):
    belief = serializers.CharField(max_length=10000, help_text="The owner's belief, in their own words.")


class GoalScoutLabelsSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True, help_text="A short suggested name, or empty.")
    area = serializers.CharField(allow_blank=True, help_text="A suggested product area, or empty.")


class GoalScoutGuardrailRequestSerializer(serializers.Serializer):
    goal = serializers.CharField(max_length=500, help_text="What the owner wants to change, in their own words.")
    measure = serializers.CharField(allow_blank=True, max_length=32, help_text="Short ID of the chosen measure.")


class GoalScoutGuardrailOptionSerializer(serializers.Serializer):
    insight = serializers.CharField(help_text="Short ID of the insight for this guardrail.")
    name = serializers.CharField(help_text="Name of the guardrail measure.")
    definition = serializers.CharField(help_text="What the guardrail counts.")
    direction = serializers.ChoiceField(
        choices=GoalScoutDirection.choices, help_text="Which way is better for this guardrail."
    )
