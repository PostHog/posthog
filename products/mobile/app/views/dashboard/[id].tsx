import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { DashboardScreen } from '@/features/views/dashboard/DashboardScreen'
import { displayModeParam, viewEntryParam } from '@/features/views/viewRoutes'
import { useWidgetOpenedEvent, widgetFamilyParam } from '@/features/widgets/useWidgetOpenedEvent'

export default function DashboardRoute(): ReactElement {
    const { id, from, mode, family } = useLocalSearchParams<{
        id: string
        from?: string
        mode?: string
        family?: string
    }>()
    const entry = viewEntryParam(from)
    useWidgetOpenedEvent('dashboard', entry, widgetFamilyParam(family))
    return <DashboardScreen dashboardRef={id ?? ''} from={entry} displayMode={displayModeParam(mode)} />
}
