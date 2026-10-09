import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { ReportScreen } from '@/features/report/ReportScreen'

export default function ReportRoute(): ReactElement {
    const { id } = useLocalSearchParams<{ id: string }>()
    return <ReportScreen reportId={id ?? ''} />
}
