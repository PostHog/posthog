import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { McpDateFilter } from './components/McpDateFilter'
import { McpSharedFilters } from './components/McpSharedFilters'
import { PEOPLE_DEFAULT_DATE_FILTER } from './people/mcpPeopleLogic'
import { PersonReport } from './people/PersonReport'
import { type PersonReportLogicProps, personReportLogic } from './people/personReportLogic'

export const scene: SceneExport<PersonReportLogicProps> = {
    component: MCPAnalyticsPerson,
    logic: personReportLogic,
    paramsToProps: ({ params: { distinctId }, searchParams }) => ({
        distinctId: decodeURIComponent(distinctId ?? ''),
        dateFrom:
            typeof searchParams.date_from === 'string' ? searchParams.date_from : PEOPLE_DEFAULT_DATE_FILTER.dateFrom,
        dateTo: typeof searchParams.date_to === 'string' ? searchParams.date_to : null,
    }),
}

export function MCPAnalyticsPerson(): JSX.Element {
    const { distinctId, dateRange } = useValues(personReportLogic)
    const { loadAll } = useActions(personReportLogic)
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
                description={null}
                resourceType={{ type: 'mcp_analytics' }}
                forceBackTo={{
                    name: 'People',
                    path: combineUrl(urls.mcpAnalyticsPeople(), {
                        date_from: dateFrom ?? undefined,
                        date_to: dateTo ?? undefined,
                    }).url,
                    key: 'mcp-analytics-people',
                }}
            />
            <div className="flex flex-wrap items-center gap-3 px-4 pb-2">
                <McpSharedFilters
                    pageKey="mcp-person"
                    dataAttrPrefix="mcp-person"
                    onRefresh={loadAll}
                    refreshing={false}
                >
                    <McpDateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                        dataAttr="mcp-person-date-filter"
                    />
                </McpSharedFilters>
            </div>
            <div className="px-4 pb-4" data-quill>
                <PersonReport />
            </div>
        </SceneContent>
    )
}
