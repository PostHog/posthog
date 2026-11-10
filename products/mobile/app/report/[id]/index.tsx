import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { ReportScreen } from '@/features/report/ReportScreen'
import { reportOpenSourceParam } from '@/features/report/reportAnalytics'
import { reportLinkFromParams, routeParam } from '@/features/report/reportLinkScope'

export default function ReportRoute(): ReactElement {
    const params = useLocalSearchParams()
    return (
        <ReportScreen
            reportId={routeParam(params.id) ?? ''}
            from={reportOpenSourceParam(params.from)}
            link={reportLinkFromParams(params)}
        />
    )
}
