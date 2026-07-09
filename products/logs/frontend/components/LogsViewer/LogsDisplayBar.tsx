import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { logsGroupByLogic } from 'products/logs/frontend/components/LogsGroupBy/logsGroupByLogic'
import { logsPatternsLogic } from 'products/logs/frontend/components/LogsPatterns/logsPatternsLogic'
import type { GroupBySourceEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { logsViewerConfigLogic } from './config/logsViewerConfigLogic'
import { LogsViewerToolbar } from './LogsViewerToolbar'

// Maps the picker's taxonomic group onto the group-by endpoint's source vocabulary.
const TAXONOMIC_GROUP_TO_SOURCE: Partial<Record<TaxonomicFilterGroupType, GroupBySourceEnumApi>> = {
    [TaxonomicFilterGroupType.Logs]: 'column',
    [TaxonomicFilterGroupType.LogAttributes]: 'log',
    [TaxonomicFilterGroupType.LogResourceAttributes]: 'resource',
}

export interface LogsDisplayBarProps {
    id: string
    // Whether to render the facet-rail collapse toggle in the frame (facet-rail layout only).
    showFacetRailToggle?: boolean
    totalLogsCount?: number
}

/**
 * The bar above the results, grouped by scope rather than by widget kind:
 *
 *  - persistent-left "frame": controls that belong to the results region in *every* lens —
 *    the filters toggle, the Logs⇄Patterns⇄Group switch, and a lens-aware count indicator.
 *  - lens configuration: the group-by key picker, shown only in Group mode (the mode lives
 *    in the segmented bar; the key is that mode's setting, like Patterns owns its mining).
 *  - contextual-right: the Logs-only presentation tools (sort, wrap, timezone, export,
 *    shortcuts), hidden in Patterns/Group modes where none of them apply.
 *
 * Sits below the sparkline, next to the table it affects.
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
    // Group is a third view like Patterns: the mode lives in the segmented bar; the key
    // picker below is the mode's configuration. Double-gated so it's unreachable flag-off.
    const inGroupByMode = showGroupBy && viewMode === 'group'

    // Each lens joins the bar behind its own flag; the bar renders once any non-Logs lens exists.
    const viewModeOptions = [
        { value: 'logs' as const, label: 'Logs' },
        ...(showPatternsView ? [{ value: 'patterns' as const, label: 'Patterns' }] : []),
        ...(showGroupBy ? [{ value: 'group' as const, label: 'Group' }] : []),
    ]

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
                {viewModeOptions.length > 1 && (
                    <LemonSegmentedButton
                        size="small"
                        value={viewMode}
                        onChange={setViewMode}
                        options={viewModeOptions}
                    />
                )}
                {inGroupByMode && (
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
                        value={groupBy?.key}
                        onChange={(value, groupType) =>
                            // Clearing the key keeps you in the Group view (empty state) — leaving
                            // the view is the segmented bar's job, not the picker's.
                            setGroupBy(
                                value ? { key: value, source: TAXONOMIC_GROUP_TO_SOURCE[groupType] ?? 'log' } : null
                            )
                        }
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
                ) : inGroupByMode ? (
                    <GroupsCountIndicator id={id} />
                ) : (
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

/**
 * Lens-aware count for Group mode, mirroring PatternsCountIndicator: mounted only while the
 * Group view is active so `logsGroupByLogic` (and its query) stays down otherwise.
 */
const GroupsCountIndicator = ({ id }: { id: string }): JSX.Element | null => {
    const { groupByResponse } = useValues(logsGroupByLogic({ id }))

    if (groupByResponse.total_groups === 0) {
        return null
    }

    return <span className="text-muted text-xs">{humanFriendlyNumber(groupByResponse.total_groups)} groups</span>
}
