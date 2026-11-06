import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { ProjectScopeOverride } from '@/auth/projectScope'
import { ReportDetailsScreen } from '@/features/report/details/ReportDetailsScreen'
import { reportLinkFromParams, routeParam, useReportLinkScope } from '@/features/report/reportLinkScope'

export default function ReportDetailsRoute(): ReactElement {
    const params = useLocalSearchParams()
    const linkScope = useReportLinkScope(reportLinkFromParams(params))
    return (
        <ProjectScopeOverride.Provider value={linkScope.kind === 'scope' ? linkScope.override : null}>
            <ReportDetailsScreen reportId={routeParam(params.id) ?? ''} />
        </ProjectScopeOverride.Provider>
    )
}
