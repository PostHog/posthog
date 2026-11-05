import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { ReportScreen } from '@/features/report/ReportScreen'
import { reportOpenSourceParam } from '@/features/report/reportAnalytics'

/** A repeated query parameter arrives as an array, which the route types do not describe. Such a link is malformed. */
function single(value: string | string[] | undefined): string | undefined {
    return typeof value === 'string' ? value : undefined
}

export default function ReportRoute(): ReactElement {
    const params = useLocalSearchParams()
    const project = single(params.project)
    const host = single(params.host)
    const projectId = project !== undefined && /^\d+$/.test(project) ? Number(project) : null
    return (
        <ReportScreen
            reportId={single(params.id) ?? ''}
            from={reportOpenSourceParam(params.from)}
            link={{ projectId, host: host?.toLowerCase() || null }}
        />
    )
}
