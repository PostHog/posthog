import { useValues } from 'kea'

import { useApmMobileLayout } from 'lib/hooks/useApmMobileLayout'
import { cn } from 'lib/utils/css-classes'

import { LogsViewerScope } from 'products/logs/frontend/components/LogsViewer/config/types'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { LogsFullScreenButton } from 'products/logs/frontend/components/LogsViewer/LogsFullScreenButton'
import { SavedViewsButton } from 'products/logs/frontend/components/LogsViews/SavedViewsButton'

import { FilterHistoryDropdown } from '../FilterHistoryDropdown'
import { LogsAppliedFilters, LogsFilterGroup, LogsFilterSearch, LogsQueryControls } from './LogsFilterBar'

/**
 * Top toolbar for the facet-rail layout — the "ask a question" controls: search, time range, refresh,
 * live tail, saved views and filter history. Sits above the sparkline (its inputs produce the sparkline
 * + table). View controls (sort, wrap, export, …) live in LogsDisplayBar below the sparkline.
 *
 * Level + Service aren't here — they're facets in the rail. The active-filter chips render under the bar.
 */
export const LogsQueryBar = ({
    showSavedViewsButton = false,
    showFullScreenButton = false,
    autoFocusSearch = true,
    scope,
}: {
    showSavedViewsButton?: boolean
    showFullScreenButton?: boolean
    autoFocusSearch?: boolean
    scope?: LogsViewerScope
}): JSX.Element => {
    const { id } = useValues(logsViewerFiltersLogic)
    const mobileLayout = useApmMobileLayout()

    return (
        <LogsFilterGroup>
            <div className="flex flex-col gap-2 w-full">
                <div className="flex gap-2 flex-wrap w-full justify-between">
                    <div
                        className={cn(
                            'flex gap-1.5',
                            mobileLayout ? 'min-w-0 w-full sm:w-auto sm:flex-1 sm:min-w-[220px]' : 'shrink-0 flex-1'
                        )}
                    >
                        <div className={cn('flex-1', mobileLayout ? 'min-w-0' : 'min-w-[300px]')}>
                            <LogsFilterSearch autoFocus={autoFocusSearch && !mobileLayout} />
                        </div>
                        <FilterHistoryDropdown />
                        {showSavedViewsButton && <SavedViewsButton id={id} iconOnly />}
                    </div>
                    <div className="flex gap-1.5 min-w-0">
                        <LogsQueryControls />
                        {showFullScreenButton && <LogsFullScreenButton id={id} scope={scope} />}
                    </div>
                </div>
                <LogsAppliedFilters />
            </div>
        </LogsFilterGroup>
    )
}
