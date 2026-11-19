import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'
import { webTileParam } from '@/features/views/viewRoutes'
import { WebBreakdownListScreen } from '@/features/views/webAnalytics/WebBreakdownListScreen'
import type { WebBreakdown } from '@/model/views'

export default function WebAnalyticsListRoute(): ReactElement {
    const { tile, breakdown } = useLocalSearchParams<{ tile?: string; breakdown?: string }>()
    // The screen checks the breakdown against the tile's tabs, so an unknown value falls back to the first tab.
    return <WebBreakdownListScreen tile={webTileParam(tile)} breakdown={(breakdown as WebBreakdown) ?? null} />
}
