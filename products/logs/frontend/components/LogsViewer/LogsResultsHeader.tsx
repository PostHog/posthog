import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight, IconList, IconStack } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { PatternsResultCount } from '../LogsPatterns/LogsPatterns'
import { logsViewerConfigLogic } from './config/logsViewerConfigLogic'
import { LogsViewerToolbar, LogsViewerToolbarProps } from './LogsViewerToolbar'

export interface LogsResultsHeaderProps {
    id: string
    toolbarProps: LogsViewerToolbarProps
}

/**
 * The bar above the results, split into two zones:
 *  - persistent left (both views): show/hide filters, the Logs/Patterns switch, the result count
 *  - view-specific right: the active view's controls (Logs: Live tail + sort/wrap/export; Patterns: none yet)
 */
export const LogsResultsHeader = ({ id, toolbarProps }: LogsResultsHeaderProps): JSX.Element => {
    const showPatternsView = useFeatureFlag('LOGS_PATTERNS_VIEW')
    const showFacetRail = useFeatureFlag('LOGS_FACET_RAIL')
    const { viewMode, facetRailCollapsed } = useValues(logsViewerConfigLogic)
    const { setViewMode, setFacetRailCollapsed } = useActions(logsViewerConfigLogic)

    const inPatternsMode = showPatternsView && viewMode === 'patterns'

    const resultsCount = inPatternsMode ? (
        <PatternsResultCount id={id} />
    ) : toolbarProps.totalLogsCount !== undefined && toolbarProps.totalLogsCount > 0 ? (
        <span className="text-muted text-xs">{humanFriendlyNumber(toolbarProps.totalLogsCount)} logs</span>
    ) : null

    return (
        <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
                {showFacetRail && (
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
                            { value: 'logs', label: 'Logs', icon: <IconList /> },
                            { value: 'patterns', label: 'Patterns', icon: <IconStack /> },
                        ]}
                    />
                )}
                {resultsCount}
            </div>
            {!inPatternsMode && <LogsViewerToolbar {...toolbarProps} />}
        </div>
    )
}
