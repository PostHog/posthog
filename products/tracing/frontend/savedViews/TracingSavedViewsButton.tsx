import { useValues } from 'kea'

import { SavedViewsButton } from 'lib/components/SavedViews/SavedViewsButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { getTracingFiltersSummaryLines } from './savedViewsSummary'
import { TRACING_SAVED_VIEWS_LOGIC_PROPS, tracingViewsLogic } from './tracingViewsLogic'

function TracingSavedViewsButtonInner(): JSX.Element {
    const { savePayload } = useValues(tracingViewsLogic)

    return (
        <SavedViewsButton
            logicProps={TRACING_SAVED_VIEWS_LOGIC_PROPS}
            savePayload={savePayload}
            getFiltersSummaryLines={getTracingFiltersSummaryLines}
            data-attr="tracing-saved-views-button"
        />
    )
}

export function TracingSavedViewsButton(): JSX.Element | null {
    const enabled = useFeatureFlag('TRACING_SAVED_VIEWS')

    if (!enabled) {
        return null
    }

    return <TracingSavedViewsButtonInner />
}
