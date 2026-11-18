import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { InsightScreen } from '@/features/views/insight/InsightScreen'
import { displayModeParam, numberParam, viewEntryParam } from '@/features/views/viewRoutes'
import { useWidgetOpenedEvent, widgetFamilyParam } from '@/features/widgets/useWidgetOpenedEvent'

export default function InsightRoute(): ReactElement {
    const { shortId, fromDashboard, insightId, from, mode, family } = useLocalSearchParams<{
        shortId: string
        fromDashboard?: string
        insightId?: string
        from?: string
        mode?: string
        family?: string
    }>()
    const entry = viewEntryParam(from)
    useWidgetOpenedEvent('insight', entry, widgetFamilyParam(family))
    return (
        <InsightScreen
            shortId={shortId ?? ''}
            fromDashboard={fromDashboard || null}
            insightId={numberParam(insightId)}
            from={entry}
            displayMode={displayModeParam(mode)}
        />
    )
}
