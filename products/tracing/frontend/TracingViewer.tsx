import { BindLogic } from 'kea'

import type { AggregatedSpanRow, DateRange } from '~/queries/schema/schema-general'
import type { UniversalFiltersGroup } from '~/types'

import { tracingConfigLogic } from './tracingConfigLogic'
import { tracingDataLogic } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import { TracingViewerContent } from './TracingViewerContent'
import { tracingViewerLogic } from './tracingViewerLogic'

export interface TracingViewerProps {
    id: string
    pinnedFilters?: UniversalFiltersGroup
    autoLoad?: boolean
    /** Enable this only from the /tracing scene. The saved-views logics always bind the scene's
     *  viewer instance, so a viewer under any other `id` would read and write the scene's filters
     *  instead of its own. */
    showSavedViewsButton?: boolean
    onOperationClick?: (row: AggregatedSpanRow, dateRange: DateRange) => void
}

export function TracingViewer({
    id,
    pinnedFilters,
    autoLoad = true,
    showSavedViewsButton = false,
    onOperationClick,
}: TracingViewerProps): JSX.Element {
    return (
        <BindLogic logic={tracingFiltersLogic} props={{ id, pinnedFilters }}>
            <BindLogic logic={tracingDataLogic} props={{ id, autoLoad }}>
                <BindLogic logic={tracingViewerLogic} props={{ id }}>
                    <BindLogic logic={tracingConfigLogic} props={{ id }}>
                        <TracingViewerContent
                            id={id}
                            showSavedViewsButton={showSavedViewsButton}
                            onOperationClick={onOperationClick}
                        />
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
