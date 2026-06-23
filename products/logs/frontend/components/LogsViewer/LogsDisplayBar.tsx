import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { logsViewerConfigLogic } from './config/logsViewerConfigLogic'
import { LogsViewerToolbar, LogsViewerToolbarProps } from './LogsViewerToolbar'

/**
 * Bottom toolbar for the facet-rail layout — the "operate on the data" controls: the rail toggle plus
 * the result-view controls (sort, wrap, timezone, export, fullscreen, count). Sits below the sparkline,
 * next to the table it affects. None of these re-run the query; they only change how results render.
 */
export const LogsDisplayBar = (props: LogsViewerToolbarProps): JSX.Element => {
    const { facetRailCollapsed } = useValues(logsViewerConfigLogic)
    const { setFacetRailCollapsed } = useActions(logsViewerConfigLogic)

    return (
        <div className="flex items-start gap-2">
            <LemonButton
                size="small"
                icon={facetRailCollapsed ? <IconChevronRight /> : <IconChevronLeft />}
                onClick={() => setFacetRailCollapsed(!facetRailCollapsed)}
                aria-label={facetRailCollapsed ? 'Show filters' : 'Hide filters'}
            >
                {facetRailCollapsed ? 'Show filters' : 'Hide filters'}
            </LemonButton>
            <div className="flex-1 min-w-0">
                <LogsViewerToolbar {...props} />
            </div>
        </div>
    )
}
