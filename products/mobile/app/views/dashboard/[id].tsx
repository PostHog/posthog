import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { DashboardScreen } from '@/features/views/dashboard/DashboardScreen'
import { displayModeParam, viewEntryParam } from '@/features/views/viewRoutes'

export default function DashboardRoute(): ReactElement {
    const { id, from, mode } = useLocalSearchParams<{ id: string; from?: string; mode?: string }>()
    return <DashboardScreen dashboardRef={id ?? ''} from={viewEntryParam(from)} displayMode={displayModeParam(mode)} />
}
