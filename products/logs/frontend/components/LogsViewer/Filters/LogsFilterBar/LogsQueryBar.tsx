import { useValues } from 'kea'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { SavedViewsButton } from 'products/logs/frontend/components/LogsViews/SavedViewsButton'

import { FilterHistoryDropdown } from '../FilterHistoryDropdown'
import {
    LogsAppliedFilters,
    LogsFilterGroup,
    LogsFilterSearch,
    LogsFullScreenButton,
    LogsQueryControls,
} from './LogsFilterBar'

/**
 * Top toolbar for the facet-rail layout — the "ask a question" controls: search, time range, refresh,
 * saved views, filter history and fullscreen. Sits above the sparkline (its inputs produce the sparkline
 * + table). View-specific controls (Live tail, sort, wrap, export, …) live in the results header below
 * the sparkline.
 *
 * Level + Service aren't here — they're facets in the rail. The active-filter chips render under the bar.
 */
export const LogsQueryBar = ({
    showSavedViewsButton = false,
    onOpenFullScreen,
}: {
    showSavedViewsButton?: boolean
    onOpenFullScreen?: () => void
}): JSX.Element => {
    const { id } = useValues(logsViewerFiltersLogic)

    return (
        <LogsFilterGroup>
            <div className="flex flex-col gap-2 w-full bg-primary">
                <div className="flex gap-2 flex-wrap w-full justify-between">
                    <div className="flex shrink-0 flex-1 gap-1.5">
                        <div className="flex-1 min-w-[300px]">
                            <LogsFilterSearch />
                        </div>
                        <FilterHistoryDropdown />
                        {showSavedViewsButton && <SavedViewsButton id={id} iconOnly />}
                    </div>
                    <div className="flex gap-1.5">
                        <LogsQueryControls />
                        <LogsFullScreenButton onOpenFullScreen={onOpenFullScreen} />
                    </div>
                </div>
                <LogsAppliedFilters />
            </div>
        </LogsFilterGroup>
    )
}
