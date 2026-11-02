import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { InsightScreen } from '@/features/views/insight/InsightScreen'
import { displayModeParam, numberParam, viewEntryParam } from '@/features/views/viewRoutes'

export default function InsightRoute(): ReactElement {
    const { shortId, fromDashboard, insightId, from, mode } = useLocalSearchParams<{
        shortId: string
        fromDashboard?: string
        insightId?: string
        from?: string
        mode?: string
    }>()
    return (
        <InsightScreen
            shortId={shortId ?? ''}
            fromDashboard={fromDashboard || null}
            insightId={numberParam(insightId)}
            from={viewEntryParam(from)}
            displayMode={displayModeParam(mode)}
        />
    )
}
