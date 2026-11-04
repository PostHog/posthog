import { BindLogic, useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { PageReportTab, pageReportsLogic } from 'scenes/web-analytics/pageReportsLogic'

import { PageHealthCards } from './PageHealthCards'
import { PageReportAiTab } from './PageReportAiTab'
import { pageReportDetailLogic } from './pageReportDetailLogic'
import { PageReportHeader } from './PageReportHeader'
import { PageReportSearchTab } from './PageReportSearchTab'
import { pageKeyForUrl } from './pageReportsUtils'
import { PageReportTileRows } from './PageReportTileRows'

export function PageReportDetail({ pageUrl }: { pageUrl: string }): JSX.Element {
    const { pageReportTab, tilesByTab, isPathCleaningEnabled, pathCleaningFilters, selectedHost } =
        useValues(pageReportsLogic)
    const { setPageReportTab } = useActions(pageReportsLogic)
    const pageKey = pageKeyForUrl(pageUrl, isPathCleaningEnabled, pathCleaningFilters, selectedHost)

    const tileTab = (tab: PageReportTab): JSX.Element => <PageReportTileRows rows={tilesByTab[tab] ?? []} />

    return (
        <BindLogic logic={pageReportDetailLogic} props={{ pageKey, pageUrl }}>
            <div className="flex flex-col gap-3 mt-2 pb-24" data-attr="page-report-detail">
                <PageReportHeader pageKey={pageKey} pageUrl={pageUrl} selectedHost={selectedHost} />
                <PageHealthCards />
                <LemonTabs
                    activeKey={pageReportTab}
                    onChange={setPageReportTab}
                    data-attr="page-report-tabs"
                    tabs={[
                        { key: PageReportTab.Overview, label: 'Overview', content: tileTab(PageReportTab.Overview) },
                        { key: PageReportTab.Traffic, label: 'Traffic', content: tileTab(PageReportTab.Traffic) },
                        {
                            key: PageReportTab.Search,
                            label: 'Search',
                            content: <PageReportSearchTab />,
                        },
                        { key: PageReportTab.AI, label: 'AI', content: <PageReportAiTab /> },
                        { key: PageReportTab.Audience, label: 'Audience', content: tileTab(PageReportTab.Audience) },
                    ]}
                />
            </div>
        </BindLogic>
    )
}
