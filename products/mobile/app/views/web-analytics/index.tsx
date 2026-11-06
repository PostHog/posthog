import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { viewEntryParam } from '@/features/views/viewRoutes'
import { WebAnalyticsScreen } from '@/features/views/webAnalytics/WebAnalyticsScreen'

export default function WebAnalyticsRoute(): ReactElement {
    const { from } = useLocalSearchParams<{ from?: string }>()
    return <WebAnalyticsScreen from={viewEntryParam(from)} />
}
