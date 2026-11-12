from temporalio import activity

from products.replay_vision.backend.temporal.activities.advance_scanner_watermark import advance_scanner_watermark
from products.replay_vision.backend.temporal.activities.check_scanner_budget import check_scanner_budget
from products.replay_vision.backend.temporal.activities.count_in_flight_applies import count_in_flight_applies
from products.replay_vision.backend.temporal.activities.find_scanner_candidates import find_scanner_candidates
from products.replay_vision.backend.temporal.constants import in_flight_headroom
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome
from products.replay_vision.backend.temporal.sweep_types import (
    CheckScannerBudgetInputs,
    CountInFlightAppliesInputs,
    FindScannerCandidatesInputs,
    SweepScannerInputs,
    SweepScannerTickOutput,
    watermark_advance,
)


@activity.defn
@track_activity()
def sweep_scanner_tick_activity(inputs: SweepScannerInputs) -> SweepScannerTickOutput:
    """Temporal bills each scheduled activity, and most ticks find nothing, so an empty tick ends here.

    A tick with candidates leaves the watermark to the workflow, which must start the children first.
    """
    try:
        budget = check_scanner_budget(CheckScannerBudgetInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id))
        if budget.capped:
            return SweepScannerTickOutput()
    except Exception:
        # Fails open because admissions stay gated at the persistence boundary.
        record_sweep_outcome("scanner_budget_check_failed")
        activity.logger.warning(
            "replay_vision.scanner_budget_check_failed", extra={"scanner_id": str(inputs.scanner_id)}, exc_info=True
        )

    try:
        in_flight = count_in_flight_applies(
            CountInFlightAppliesInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id)
        )
    except Exception:
        # Ends the tick rather than retrying it or dispatching against an unknown load; the next tick counts again.
        record_sweep_outcome("in_flight_count_failed")
        activity.logger.warning(
            "replay_vision.in_flight_count_failed", extra={"scanner_id": str(inputs.scanner_id)}, exc_info=True
        )
        return SweepScannerTickOutput()
    headroom = in_flight_headroom(in_flight.scanner, in_flight.team)
    if headroom <= 0:
        # At a cap, so drain before fetching more. The watermark holds and the next tick resumes from it.
        activity.logger.info(
            "replay_vision.sweep_throttled",
            extra={
                "scanner_id": str(inputs.scanner_id),
                "scanner_in_flight": in_flight.scanner,
                "team_in_flight": in_flight.team,
            },
        )
        return SweepScannerTickOutput()

    found = find_scanner_candidates(
        FindScannerCandidatesInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id, candidate_limit=headroom)
    )
    if found.candidates or found.deep_candidates or found.priming_candidates:
        return SweepScannerTickOutput(dispatch=found)

    advance = watermark_advance(inputs.scanner_id, found)
    if advance is not None:
        advance_scanner_watermark(advance)
    return SweepScannerTickOutput()
