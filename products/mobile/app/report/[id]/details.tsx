import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { ReportDetailsScreen } from '@/features/report/details/ReportDetailsScreen'

export default function ReportDetailsRoute(): ReactElement {
    const { id } = useLocalSearchParams<{ id: string }>()
    return <ReportDetailsScreen reportId={id ?? ''} />
}
