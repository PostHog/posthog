import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { ReportScreen } from '@/features/report/ReportScreen'
import { reportOpenSourceParam } from '@/features/report/reportAnalytics'

export default function ReportRoute(): ReactElement {
    const { id, from, project, host } = useLocalSearchParams<{
        id: string
        from?: string
        project?: string
        host?: string
    }>()
    const projectId = project !== undefined && /^\d+$/.test(project) ? Number(project) : null
    return (
        <ReportScreen
            reportId={id ?? ''}
            from={reportOpenSourceParam(from)}
            link={{ projectId, host: host?.toLowerCase() || null }}
        />
    )
}
