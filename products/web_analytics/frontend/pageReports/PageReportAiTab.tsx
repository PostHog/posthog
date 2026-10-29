import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { TileId } from 'scenes/web-analytics/common'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { createPagePerformanceInsightProps } from 'scenes/web-analytics/pagePerformanceLogic'

import { QueryContext } from '~/queries/types'

import { AiAssistantList } from 'products/web_analytics/frontend/searchAndAi/AiAssistantList'
import { AiTableCard } from 'products/web_analytics/frontend/searchAndAi/AiTableCard'
import { AiTrendCard } from 'products/web_analytics/frontend/searchAndAi/AiTrendCard'
import { CRAWLER_COLUMNS } from 'products/web_analytics/frontend/searchAndAi/crawlerColumns'
import { SearchAndAiLoading } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiLoading'
import { SearchAndAiQuery } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiQuery'
import { SearchAndAiSectionHeading } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiSectionHeading'

import { pageReportDetailLogic } from './pageReportDetailLogic'

const SERVER_LOGS_DOCS_URL = 'https://posthog.com/docs/web-analytics/sending-http-logs'
const PAGE_REPORT_SCOPE = 'page-report'

const crawlersInsightProps = createPagePerformanceInsightProps(TileId.AI_CRAWLERS, PAGE_REPORT_SCOPE)
const crawlersContext: QueryContext = {
    columns: CRAWLER_COLUMNS,
    emptyStateHeading: 'No AI crawlers read this page',
}

export function PageReportAiTab(): JSX.Element {
    const {
        aiAssistants,
        aiAssistantsLoading,
        aiCrawlersQuery,
        aiLandingPagesQuery,
        aiReferralTrendQuery,
        crawlTrendQuery,
        crawlersMeasured,
        failedLoads,
        healthFailed,
    } = useValues(pageReportDetailLogic)
    const { loadAiAssistants } = useActions(pageReportDetailLogic)

    return (
        <div className="flex flex-col gap-6" data-attr="page-report-ai-tab">
            <section>
                <SearchAndAiSectionHeading description="People who landed on this page from an AI assistant such as ChatGPT, Claude, or Perplexity.">
                    Traffic from AI
                </SearchAndAiSectionHeading>
                <div className="flex flex-col gap-4">
                    <AiTrendCard
                        title="Referrals over time"
                        query={aiReferralTrendQuery}
                        tileId={TileId.AI_REFERRALS_TREND}
                        uniqueKey="page-report-ai-referrals-trend"
                        scope={PAGE_REPORT_SCOPE}
                    />
                    <div className="grid grid-cols-1 @min-[64rem]/main-content:grid-cols-2 gap-4">
                        <PagePerformanceCard
                            title="By assistant"
                            className="min-w-0"
                            footer="Some assistants strip the referrer, so this is a lower bound."
                        >
                            <AiAssistantList
                                rows={aiAssistants}
                                loading={aiAssistantsLoading}
                                emptyText="No visitors arrived from an AI assistant in this period."
                                failed={failedLoads.aiAssistants}
                                onRetry={() => loadAiAssistants(null)}
                            />
                        </PagePerformanceCard>
                        <AiTableCard
                            title="Where AI visitors started"
                            query={aiLandingPagesQuery}
                            tileId={TileId.AI_LANDING_PAGES}
                            scope={PAGE_REPORT_SCOPE}
                            tableLayout="auto"
                            footer="The first page people opened after arriving from an AI assistant, on visits that went on to reach this page. If it's this page, they came straight here."
                        />
                    </div>
                </div>
            </section>
            <section>
                <SearchAndAiSectionHeading description="Bots that read this page to train a model or to answer someone's question about it.">
                    AI crawlers
                </SearchAndAiSectionHeading>
                {crawlersMeasured === false ? (
                    <LemonBanner type="info">
                        AI crawlers don't run the PostHog snippet, so they only show up when your server logs are
                        forwarded to PostHog.{' '}
                        <Link to={SERVER_LOGS_DOCS_URL} target="_blank">
                            Learn how to forward server logs
                        </Link>
                    </LemonBanner>
                ) : crawlersMeasured === null && !healthFailed ? (
                    <SearchAndAiLoading loading label="Checking for server logs" className="min-h-64" />
                ) : (
                    <div className="flex flex-col gap-4">
                        <AiTrendCard
                            title="Crawler activity over time"
                            query={crawlTrendQuery}
                            tileId={TileId.AI_CRAWLERS_TREND}
                            uniqueKey="page-report-ai-crawl-trend"
                            scope={PAGE_REPORT_SCOPE}
                        />
                        <PagePerformanceCard
                            title="By crawler"
                            footer="Crawlers are bots that read the page for AI models. They are not counted as visitors."
                        >
                            <SearchAndAiQuery
                                uniqueKey="page-report-ai-crawlers"
                                query={aiCrawlersQuery}
                                insightProps={crawlersInsightProps}
                                context={crawlersContext}
                            />
                        </PagePerformanceCard>
                    </div>
                )}
            </section>
        </div>
    )
}
