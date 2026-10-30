import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { ReportScreen } from '@/features/report/ReportScreen'
import { reportOpenSourceParam } from '@/features/report/reportAnalytics'

export default function ReportRoute(): ReactElement {
    const { id, from } = useLocalSearchParams<{ id: string; from?: string }>()
    return <ReportScreen reportId={id ?? ''} from={reportOpenSourceParam(from)} />
}
