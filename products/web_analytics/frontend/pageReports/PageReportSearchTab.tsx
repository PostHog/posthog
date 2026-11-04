import { useActions, useMountedLogic, useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { createPagePerformanceInsightProps } from 'scenes/web-analytics/pagePerformanceLogic'

import { GoogleSearchConsoleKeywords } from 'products/web_analytics/frontend/searchAndAi/GoogleSearchConsoleKeywords'
import { SearchAndAiQuery } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiQuery'

import { pageReportDetailLogic } from './pageReportDetailLogic'

const keywordsInsightProps = createPagePerformanceInsightProps(TileId.PAGE_PERFORMANCE_TABLE, 'page-report-keywords')
const googleTrendInsightProps = createPagePerformanceInsightProps(TileId.PAGE_PERFORMANCE_TABLE, 'page-report-google')

export function PageReportSearchTab(): JSX.Element {
    const { googleTrendQuery, window, isPathCleaningEnabled, currentTeam } = useValues(pageReportDetailLogic)
    const { props } = useMountedLogic(pageReportDetailLogic)
    const { clickSearchConsoleConnect } = useActions(pageReportDetailLogic)

    return (
        <div
            className="grid grid-cols-1 @min-[64rem]/main-content:grid-cols-2 gap-3"
            data-attr="page-report-search-tab"
        >
            <PagePerformanceCard title="Visitors from Google search">
                <div className="min-h-72 flex flex-col">
                    <SearchAndAiQuery
                        uniqueKey="page-report-google-trend"
                        query={googleTrendQuery}
                        insightProps={googleTrendInsightProps}
                    />
                </div>
            </PagePerformanceCard>
            <PagePerformanceCard
                title="Top search queries"
                footer="Queries this page ranks for in Google, with clicks and average position from Google Search Console."
            >
                <GoogleSearchConsoleKeywords
                    page={props.pageKey}
                    window={window}
                    isPathCleaningEnabled={isPathCleaningEnabled}
                    pathCleaningFilters={currentTeam?.path_cleaning_filters}
                    insightProps={keywordsInsightProps}
                    uniqueKey="page-report-gsc-keywords"
                    onConnectClick={clickSearchConsoleConnect}
                />
            </PagePerformanceCard>
        </div>
    )
}
