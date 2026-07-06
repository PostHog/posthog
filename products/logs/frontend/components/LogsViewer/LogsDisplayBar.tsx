import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { logsPatternsLogic } from 'products/logs/frontend/components/LogsPatterns/logsPatternsLogic'

import { logsViewerConfigLogic } from './config/logsViewerConfigLogic'
import { LogsViewerToolbar } from './LogsViewerToolbar'

export interface LogsDisplayBarProps {
    id: string
    // Whether to render the facet-rail collapse toggle in the frame (facet-rail layout only).
    showFacetRailToggle?: boolean
    totalLogsCount?: number
}

/**
 * The bar above the results, grouped by scope rather than by widget kind:
 *
 *  - persistent-left "frame": controls that belong to the results region in *both* lenses —
 *    the filters toggle, the Logs⇄Patterns switch, and a lens-aware count indicator.
 *  - contextual-right: the Logs-only presentation tools (sort, wrap, timezone, export, shortcuts),
 *    hidden entirely in Patterns mode where none of them apply.
 *
 * Sits below the sparkline, next to the table it affects. None of these re-run the query.
 */
export const LogsDisplayBar = ({
    id,
    showFacetRailToggle = false,
    totalLogsCount,
}: LogsDisplayBarProps): JSX.Element => {
    const { facetRailCollapsed, viewMode, groupBy } = useValues(logsViewerConfigLogic)
    const { setFacetRailCollapsed, setViewMode, setGroupBy } = useActions(logsViewerConfigLogic)
    const showPatternsView = useFeatureFlag('LOGS_PATTERNS_VIEW')
    const showGroupBy = useFeatureFlag('LOGS_GROUP_BY')

    const inPatternsMode = showPatternsView && viewMode === 'patterns'
    // Grouping applies to the Logs lens only; Patterns has its own aggregation.
    const inGroupByMode = showGroupBy && !inPatternsMode && groupBy !== null

    return (
        <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
                {showFacetRailToggle && (
                    <LemonButton
                        size="small"
                        icon={facetRailCollapsed ? <IconChevronRight /> : <IconChevronLeft />}
                        onClick={() => setFacetRailCollapsed(!facetRailCollapsed)}
                        aria-label={facetRailCollapsed ? 'Show filters' : 'Hide filters'}
                    >
                        {facetRailCollapsed ? 'Show filters' : 'Hide filters'}
                    </LemonButton>
                )}
                {showPatternsView && (
                    <LemonSegmentedButton
                        size="small"
                        value={viewMode}
                        onChange={setViewMode}
                        options={[
                            { value: 'logs', label: 'Logs' },
                            { value: 'patterns', label: 'Patterns' },
                        ]}
                    />
                )}
                {showGroupBy && !inPatternsMode && (
                    <TaxonomicStringPopover
                        size="small"
                        groupType={TaxonomicFilterGroupType.Logs}
                        groupTypes={[
                            TaxonomicFilterGroupType.Logs,
                            TaxonomicFilterGroupType.LogAttributes,
                            TaxonomicFilterGroupType.LogResourceAttributes,
                        ]}
                        // `message` is not a grouping key — high-cardinality free text is the
                        // Patterns lens's job. Excluding it also drops the message-search item.
                        excludedProperties={{ [TaxonomicFilterGroupType.Logs]: ['message'] }}
                        value={groupBy ?? undefined}
                        onChange={(value) => setGroupBy(value || null)}
                        allowClear
                        placeholder="Group by"
                        renderValue={(value) => (
                            <span>
                                Group by <span className="font-mono">{value}</span>
                            </span>
                        )}
                        selectingKeyOnly
                        data-attr="logs-group-by-picker"
                    />
                )}
                {inPatternsMode ? (
                    <PatternsCountIndicator id={id} />
                ) : (
                    !inGroupByMode &&
                    totalLogsCount !== undefined &&
                    totalLogsCount > 0 && (
                        <span className="text-muted text-xs">{humanFriendlyNumber(totalLogsCount)} logs</span>
                    )
                )}
            </div>
            {!inPatternsMode && !inGroupByMode && <LogsViewerToolbar totalLogsCount={totalLogsCount} />}
        </div>
    )
}

/**
 * Lens-aware count for Patterns mode. Split into its own component so `logsPatternsLogic` is only
 * mounted while Patterns is active — mounting it in Logs mode would kick off the heavier patterns query.
 */
const PatternsCountIndicator = ({ id }: { id: string }): JSX.Element | null => {
    const { patterns } = useValues(logsPatternsLogic({ id }))

    if (patterns.length === 0) {
        return null
    }

    return <span className="text-muted text-xs">{humanFriendlyNumber(patterns.length)} patterns</span>
}
