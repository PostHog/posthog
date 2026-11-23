/** One switch in the report actions section. `action` is the `ReportTaskActionKind` value the API stores. */
export interface ScoutReportActionRow {
    action: string
    label: string
    description: string
}

/**
 * The report actions a person may grant one scout, mirroring `SCOUT_GRANTABLE_REPORT_ACTIONS` in
 * `products/signals/backend/scout_report_actions.py`. Only actions whose request text is fixed are
 * grantable there, so an action added on the backend needs a row added here to be offered.
 */
export const SCOUT_REPORT_ACTION_ROWS: ScoutReportActionRow[] = [
    {
        action: 'make_it_green',
        label: 'Make it green',
        description: "Fix failing CI and merge conflicts on a report's open pull request, without merging it",
    },
    {
        action: 'resolve_conflicts',
        label: 'Resolve conflicts',
        description: "Update a report's open pull request from its base branch and resolve the conflicts",
    },
]

/** Mirrors `MAX_SCOUT_REPORT_ACTIONS_PER_DAY` in `products/signals/backend/scout_report_actions.py`. */
export const MAX_SCOUT_REPORT_ACTIONS_PER_DAY = 20

/**
 * Labels for the actions a scout holds, for the settings header and the roster tag. An action this
 * module does not know keeps its raw key, so a grant the backend adds never disappears from view.
 */
export function scoutReportActionLabels(actions: readonly string[] | undefined): string[] {
    return (actions ?? []).map(
        (action) => SCOUT_REPORT_ACTION_ROWS.find((row) => row.action === action)?.label ?? action
    )
}
