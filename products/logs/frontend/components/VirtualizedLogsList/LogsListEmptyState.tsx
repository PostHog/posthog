import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { logsDropRulesSettingsUrl } from 'products/logs/frontend/logsDropRulesSettingsUrl'
import { logsRetentionRulesSettingsUrl } from 'products/logs/frontend/logsRetentionRulesSettingsUrl'
import { logsRetentionSettingsUrl } from 'products/logs/frontend/logsRetentionSettingsUrl'
import { LOGS_RETENTION_DATE_FORMAT, LogsRetentionWindow } from 'products/logs/frontend/logsRetentionWindow'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export interface LogsListEmptyStateProps {
    /** Set when the requested range reaches back past retention, which is why the result can be empty. */
    retention?: LogsRetentionWindow | null
    onExpandTimeRange?: () => void
    /** Re-runs the search over the retained window. Offered instead of expanding the range. */
    onSearchRetainedRange?: () => void
}

/**
 * Shown when a log search resolves to nothing. A range that reaches back past retention gets its own
 * wording, because those logs were deleted and the generic "adjust your filters" advice cannot help.
 */
export function LogsListEmptyState({
    retention,
    onExpandTimeRange,
    onSearchRetainedRange,
}: LogsListEmptyStateProps): JSX.Element {
    let headline = 'No logs found'
    let body: JSX.Element | string =
        'Try adjusting your filters, expanding the time range, or checking that your app is sending logs. Drop rules can remove logs before they are stored, and retention rules can delete matching logs sooner than your default retention.'
    let settingsLink = (
        <>
            <Link to={logsDropRulesSettingsUrl()} data-attr="logs-empty-state-drop-rules">
                Check drop rules
            </Link>
            <Link to={logsRetentionRulesSettingsUrl()} data-attr="logs-empty-state-retention-rules">
                Check retention rules
            </Link>
        </>
    )
    let action = onExpandTimeRange && (
        <LemonButton type="secondary" size="small" onClick={onExpandTimeRange}>
            Expand time range
        </LemonButton>
    )

    if (retention) {
        headline = retention.coversWholeRange
            ? 'This range is older than your log retention'
            : 'Part of this range is older than your log retention'
        body = (
            <>
                Your logs are kept for <span translate="no">{retention.retentionDays}</span> days by default. Logs from
                before <span translate="no">{retention.start.format(LOGS_RETENTION_DATE_FORMAT)}</span> have been
                deleted. Retention rules can keep matching logs longer or delete them sooner. Retention is applied when
                a log is stored, so raising it does not bring older logs back.
                {!retention.coversWholeRange && ' No logs matched the rest of the range.'}
            </>
        )
        settingsLink = (
            <>
                <Link to={logsRetentionSettingsUrl()} data-attr="logs-empty-state-retention">
                    Change log retention
                </Link>
                <Link to={logsRetentionRulesSettingsUrl()} data-attr="logs-empty-state-retention-rules">
                    Check retention rules
                </Link>
            </>
        )
        action = onSearchRetainedRange && (
            <LemonButton
                type="secondary"
                size="small"
                onClick={onSearchRetainedRange}
                data-attr="logs-empty-state-search-retained"
            >
                {`Search the last ${retention.retentionDays} days`}
            </LemonButton>
        )
    }

    return (
        <div className="flex flex-col items-center gap-3 p-8 text-center h-full min-h-40">
            <HedgehogMagnifyingGlass className="w-32 h-32" />
            <div>
                <h4 className="font-semibold m-0">{headline}</h4>
                <p className="text-muted text-sm mt-1 mb-0 max-w-80">{body}</p>
                <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
                    {settingsLink}
                    <Link to="https://posthog.com/docs/logs/" target="_blank">
                        View documentation
                    </Link>
                </div>
            </div>
            {action}
        </div>
    )
}
