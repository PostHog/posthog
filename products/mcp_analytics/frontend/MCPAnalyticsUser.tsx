import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { McpDateFilter } from './components/McpDateFilter'
import { McpSharedFilters } from './components/McpSharedFilters'
import { USERS_DEFAULT_DATE_FILTER } from './users/mcpUsersLogic'
import { UserReport } from './users/UserReport'
import { type UserReportLogicProps, userReportLogic } from './users/userReportLogic'

export const scene: SceneExport<UserReportLogicProps> = {
    component: MCPAnalyticsUser,
    logic: userReportLogic,
    paramsToProps: ({ params: { distinctId }, searchParams }) => ({
        distinctId: decodeURIComponent(distinctId ?? ''),
        dateFrom:
            typeof searchParams.date_from === 'string' ? searchParams.date_from : USERS_DEFAULT_DATE_FILTER.dateFrom,
        dateTo: typeof searchParams.date_to === 'string' ? searchParams.date_to : null,
    }),
}

export function MCPAnalyticsUser(): JSX.Element {
    const { distinctId, dateRange } = useValues(userReportLogic)
    const { loadAll } = useActions(userReportLogic)
    const { date_from: dateFrom, date_to: dateTo } = dateRange
    const setDates = (from: string | null, to: string | null): void => {
        const { currentLocation } = router.values
        router.actions.replace(
            combineUrl(currentLocation.pathname, {
                ...currentLocation.searchParams,
                date_from: from ?? undefined,
                date_to: to ?? undefined,
            }).url
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={distinctId}
                className="ph-no-capture"
                description={null}
                resourceType={{ type: 'mcp_analytics' }}
                forceBackTo={{
                    name: 'Users',
                    path: combineUrl(urls.mcpAnalyticsUsers(), {
                        date_from: dateFrom ?? undefined,
                        date_to: dateTo ?? undefined,
                    }).url,
                    key: 'mcp-analytics-users',
                }}
            />
            <div className="flex flex-wrap items-center gap-3 px-4 pb-2">
                <McpSharedFilters pageKey="mcp-user" dataAttrPrefix="mcp-user" onRefresh={loadAll} refreshing={false}>
                    <McpDateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                        dataAttr="mcp-user-date-filter"
                    />
                </McpSharedFilters>
            </div>
            <div className="px-4 pb-4" data-quill>
                <UserReport />
            </div>
        </SceneContent>
    )
}
