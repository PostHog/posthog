import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { LiveScreen } from '@/features/live/LiveScreen'
import { viewEntryParam } from '@/features/views/viewRoutes'

export default function LiveRoute(): ReactElement {
    const { from } = useLocalSearchParams<{ from?: string }>()
    return <LiveScreen from={viewEntryParam(from)} chrome="stack" />
}
