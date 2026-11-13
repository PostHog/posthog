"""The health check actions of an experiment."""

from typing import Any, cast

from django.conf import settings

from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.user import User
from posthog.permissions import get_authenticator_scopes
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.scopes import scopes_not_covered

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.experiments.backend.facade.api import get_experiment_health, get_experiment_health_inputs
from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.presentation.serializers.health_checks import (
    ExperimentHealthInputsSerializer,
    ExperimentHealthSerializer,
)


class ExperimentHealthChecksMixin(TeamAndOrgViewSetMixin):
    @extend_schema(
        request=None,
        responses=ExperimentHealthSerializer,
    )
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def health(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Health check findings for this experiment: problems in its configuration and its feature flag
        that keep it from producing trustworthy results, each with a fix. `checks` gives the result of
        each check, so a check that found no problem can be told from one that did not apply or could
        not read an input.

        The checks here read the experiment, its flag, its linked metrics, the project's event and
        property definitions, the cohorts of the exposure criteria, and the changes of the flag's
        variant split since launch. The checks that read exposure counts come with the
        exposure query. The split-change check compares the split changes with the exposures only
        for exposure criteria that name an event without property filters. When the split changed
        after launch and the criteria have filters or an action, or an API key lacks `query:read`,
        it returns an info finding with the subcode `not_checked` and the cause in
        `reason`. A caller who can't view the linked flag's history (viewer access to the
        flag and, with an API key, `activity_log:read`) gets that finding for every running
        experiment, because the changes are not read. A finding that tells the reader to
        move the start date offers `move_start_date`, and `evidence.suggested_start_date` holds that
        date in UTC: set the experiment's `start_date` to it. When one variant was set to 100% of the
        split, the finding offers `end_experiment` instead.

        Two checks read whether the project received an event from its event definitions: a
        definition without `last_seen_at`, such as one Wizard wrote for a planned event, counts as
        not received. A name whose definition was deleted since launch, or in the last day for a
        draft, is not checked, because ingestion writes the definition again only when the event
        arrives. No missing definition is checked when ingestion saw none of the experiment's events
        in the last day, because ingestion can be set to skip a team. `metric_event_not_ingested`
        names each metric that
        reads an event the project never received, in the `evidence` keys `metric_N`,
        `metric_N_role` and `metric_N_events`. `exposure_criteria_cannot_match` reports a custom
        exposure event the project never received (`exposure_event_not_ingested`), a
        `$feature_flag` filter on the flag call events that requires another flag
        (`filter_on_another_flag`), and a filter on an event or person property that the project has
        no definition of, with an operator that a missing property fails
        (`filter_on_property_not_ingested`, the keys in `evidence.properties`). A property whose
        definition was ever deleted is not checked, and neither is an event property filter on an
        action or on `$groupidentify`, whose properties ingestion keeps no definitions of. An event
        or property not received is info before launch, in the first 24 hours after launch, and when
        only secondary metrics read it, and a warning otherwise. `filter_on_another_flag` is a
        warning in every state, `filter_on_property_not_ingested` also reports after the end, and
        the other findings stop at the end.

        `exposure_filters` reads the cohort filters of the exposure criteria and of the activation,
        not the test account filters. `exposure_filter_on_dynamic_cohort` is a warning in every
        state: the results use the members of a dynamic cohort at the calculation, not at exposure.
        Its subcode is `cohort_forces_variant` when a release condition of the flag that matches the
        cohort's members gives one variant, `cohort_in_release_conditions` when the release
        conditions match its members otherwise, and `evidence.cohort_ids` names the cohorts. Both
        subcodes need the exposure criteria to keep the members too, not to leave them out.

        `metric_cannot_compile` builds and compiles the query of each metric without running it, as
        the caller, so a metric that every calculation fails on shows before launch. A metric that
        reads a warehouse table or view the caller may not query is not checked for them. The finding
        names each failing metric in the `evidence` keys `metric_N`, `metric_N_role`, `metric_N_error`
        (the error class, which is also the subcode of the first metric) and `metric_N_message` (the
        compiler's message). It is a warning when a primary metric fails, also after the end, because
        the calculation after the fix reads the events up to the end. It is info otherwise. A failure
        inside ClickHouse, such as a type that the data holds, isn't found. A failing metric compiles
        again on every request. A metric that compiles is cached per caller for a day, so a cohort or
        table that is deleted after a compile can take up to a day to show.

        `metric_calculation_failed` reports each metric whose latest calculation failed, from the
        latest finished calculation that the results page shows. It leaves out a metric that
        `metric_cannot_compile` reports. The subcode is the kind of the first failure: `busy`,
        `query_limit` (the query reached the read, memory, time or length limit), `settings` (a setting of
        the metric or the experiment), `not_enough_data`, `experiment_too_old` (the experiment
        started too long ago to calculate again) or `unexpected_error`. Each metric is in the
        `evidence` keys `metric_N`, `metric_N_role`, `metric_N_failure` (the kind), `metric_N_error`
        (the limit, or the family of a setting) and `metric_N_message` (only a message that PostHog
        wrote for users), and `calculated_at` is when the calculation finished. It is a
        warning when a primary metric fails for a kind that a change fixes (`query_limit`,
        `settings`, `experiment_too_old`), also after the end, because the calculation after the fix
        reads the events up to the end. It is info otherwise. When the first failure reached the
        read, memory or time limit, `reason` names the cause that the calculation shows: `metric`
        when another metric of the same calculation completed the same read of the exposures, or
        `exposure_criteria` when every metric reached a limit and an exposure or test account filter
        makes each query read all the properties of an event, person or group. `evidence.properties`
        then names the filters. A query that read precomputed exposures doesn't apply those filters,
        so it can't get `exposure_criteria`. It is null otherwise.

        `metric_all_zero` reports a metric that reads zero in every variant, from the same latest
        finished calculation, so the results page shows "Not enough data yet" at any sample size.
        Each side of a ratio that is zero in every variant counts on its own. It reads the stored
        result and the project's event definitions, and no events. A primary metric needs 1,000
        exposures in the result and 72 hours of data, because most zeros before that are outcomes
        that take time. A retention metric counts those hours from the start of its retention
        window. The subcode is the cause of the first metric: `blank_event` (an event with an empty
        name), `event_stopped` (the project last received the event before launch, while ingestion
        still records the project), `outlier_bound` (an upper outlier bound that is 0 while some
        exposures have a value) or null when none shows a cause. `blank_event` and `outlier_bound`
        also report a secondary metric, and need only 100 exposures and 12 hours of data, because
        they read 0 at any traffic. A bound on the largest value of the exposures can't be 0 while
        one has a value, so it is no cause. Neither is a bound on a metric with breakdowns, which
        gets one bound per breakdown group. Until the end, the check leaves out a metric that uses an
        event `metric_event_not_ingested` reports. Each metric, or side of a ratio, is in the
        `evidence` keys `metric_N`, `metric_N_role`, `metric_N_side`, `metric_N_exposures` and
        `metric_N_cause`. It is a warning for a primary metric. After the end it stays a warning only
        for a cause that a setting fixes, because the calculation after the fix reads the events up
        to the end. It is info otherwise.

        A launched experiment that has not ended gets the info `stale_experiment` more than 60 days
        after its start date, when the daily calculation leaves it out, with `days_running` from the
        start date in `evidence`.
        It offers `freeze_exposure` next to `end_experiment` when the experiment can freeze exposure.

        The severity of the `some_conditions_pinned` finding follows the largest share that the
        users of the pinned release conditions make up among the users who got one variant from
        the flag, in the last 7 days, or since launch or the flag's last save if later. It reads
        the flag's calls that name the matched condition, not the experiment's exposure criteria.
        When the experiment applies the filter for internal and test users, the counts leave out the
        calls that the filter excludes, so pinned users that the filter excludes add nothing. The
        severity is info up to 5%, warning above, and no finding under 1% when at least half of the calls
        that returned a variant name a condition. The finding is info when the share is unknown,
        and `reason` says why: `not_measured` (for example an API key without
        `query:read`, or a caller denied a flag call property), `too_few_people` (under 100), or
        `evaluated_outside_flag_service` (most calls come from local evaluation, a bootstrap or
        the caller's own assignment). A pin to a variant with 0% in the split adds an info,
        because that variant's results show only the pinned users, unless the experiment
        excludes the variant from the analysis.

        Two findings say that the variants are assigned outside PostHog, as info. A running
        experiment whose flag has a 0% rollout gets `assigned_outside_flag_service` instead of
        `running_but_no_rollout` when 10 or more people got a variant from flag calls without a
        flag version that are no local evaluation, from an hour after the window starts. The
        count leaves out the calls that the filter for internal and test users excludes, when the
        experiment applies it. When
        every condition that includes users pins the variant whose key one property holds,
        `assigned_by_property` replaces `all_conditions_pinned`. When none of them includes
        everyone, so that every other user gets no variant, `closed_to_matched_users` replaces it,
        as a warning. A condition without filters, or with only filters that leave users out,
        includes everyone.

        A draft whose flag has no recorded call gets the info `new_flag_no_traffic`. The record
        is the flag's `last_called_at`, which a periodic task updates, so it trails a call. The
        check reports `not_checked` when the organization's flag calls skip the events table,
        and when the project has no active flag, because the web SDK then requests no flags.

        A running experiment whose flag is disabled gets `paused_from_experiment`, as info, when
        its latest pause or resume since launch is a pause of the experiment. Otherwise it gets
        `running_but_flag_disabled`, as a warning. A caller who can't view the linked flag's
        history gets the warning, because the pause is not read. A draft whose flag is already
        active with multiple variants gets `not_started_but_multiple_variants_rolled_out` as info.
        An ended experiment whose flag is still active with multiple variants gets no finding when
        another experiment on the flag is running or launched after the end. Otherwise it gets
        `ended_flag_shared_with_draft` as info when a draft experiment uses the flag,
        `ended_but_multiple_variants_rolled_out` as a warning when the flag's `last_called_at` is
        after the end and within the last 3 days, and `ended_flag_not_called` as info when it is
        not, from 3 days and an hour after the end, because `last_called_at` trails a call. Until
        then without such a call, or when the organization's flag calls can't be read, it gets
        `ended_flag_calls_unknown` as info.

        A running experiment whose first primary metric is a funnel gets the info
        `early_significance` (subcode `below_detectable_effect`) when a significant variant's
        difference is smaller than the smallest difference its sample can detect, while that
        sample is below the one the running time estimate plans for the minimum detectable
        effect. It reads the metric's current stored result, the one the results page shows
        after its last calculation, and the running time calculator's formula.

        A running experiment with `only_count_matured_users` on gets the info
        `metrics_not_matured` while it is younger than the conversion or retention window of
        every primary metric, because no user can count for those metrics until a window passes.
        """
        experiment: Experiment = self.get_object()
        health = get_experiment_health(
            team_id=self.team_id,
            experiment_id=experiment.id,
            reader_access=self._health_reader_access(request, experiment),
            user=request.user if isinstance(request.user, User) else None,
        )
        return Response(ExperimentHealthSerializer(health).data)

    @extend_schema(
        request=None,
        responses=ExperimentHealthInputsSerializer,
    )
    @action(
        methods=["GET"],
        detail=True,
        required_scopes=["experiment:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def health_inputs(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Staff only. The inputs that the health checks read for this reader, to debug why a finding shows or not:
        the context of the checks in `health`, the exposure query's answer that the exposure checks read, and facts
        about the project from the setup context's providers (the team's experiment defaults and which SDKs call
        flags). The exposure answer comes from the cache. When it is missing or stale, a calculation starts in the
        background and `exposures.status` says so.
        """
        if not (request.user.is_staff or settings.DEBUG or is_impersonated_session(request)):
            raise PermissionDenied("Only staff users can read the health check inputs.")
        experiment: Experiment = self.get_object()
        inputs = get_experiment_health_inputs(
            team_id=self.team_id,
            experiment_id=experiment.id,
            reader_access=self._health_reader_access(request, experiment),
            user=cast(User, request.user),
        )
        return Response(ExperimentHealthInputsSerializer(inputs).data)

    def _health_reader_access(self, request: Request, experiment: Experiment) -> ExperimentHealthReaderAccess:
        # The split history is flag history, which `activity` keeps behind the flag's own access controls and
        # `activity_log:read`. It also queries events, which a scoped token reaches only with `query:read`.
        scopes = get_authenticator_scopes(request.successful_authenticator)
        missing_scopes = (
            set()
            if scopes is None or "*" in scopes
            else set(scopes_not_covered(scopes, ["activity_log:read", "query:read"]))
        )
        can_view_flag = experiment.feature_flag_id is None or self.user_access_control.check_access_level_for_object(
            experiment.feature_flag, required_level="viewer"
        )
        restrictions = get_restricted_properties_with_group_type_index_for_team(
            user=cast(User, request.user), team_id=self.team_id
        )
        return ExperimentHealthReaderAccess(
            can_read_flag_history=bool(can_view_flag) and "activity_log:read" not in missing_scopes,
            can_query_events="query:read" not in missing_scopes,
            denied_event_properties=split_restricted_property_names(restrictions).event,
            restricted_properties=frozenset(restrictions),
        )
