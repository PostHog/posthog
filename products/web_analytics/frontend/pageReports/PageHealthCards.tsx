import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { PageReportTab } from 'scenes/web-analytics/pageReportsLogic'

import { PageHealthCard } from './PageHealthCard'
import { pageReportDetailLogic } from './pageReportDetailLogic'
import { PageVisitorsCard } from './PageVisitorsCard'

export function PageHealthCards(): JSX.Element {
    const { healthCards, healthFailed, pageMetrics, searchConsole, siteTotals } = useValues(pageReportDetailLogic)
    const { hoverHealthCard, clickHealthCard, setPageReportTab, reloadHealth } = useActions(pageReportDetailLogic)

    if (healthFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: reloadHealth }}>
                Couldn't load the health summary for this page.
            </LemonBanner>
        )
    }

    return (
        <>
            <div
                className="grid grid-cols-2 @min-[60rem]/main-content:grid-cols-4 border rounded-lg bg-surface-primary overflow-hidden divide-x divide-y @min-[60rem]/main-content:divide-y-0"
                data-attr="page-report-health-cards"
            >
                <PageVisitorsCard
                    visitors={pageMetrics?.visitors ?? null}
                    siteVisitors={siteTotals?.visitors?.current ?? null}
                    onClick={() => setPageReportTab(PageReportTab.Overview)}
                />
                {healthCards.map((card) => (
                    <PageHealthCard
                        key={card.key}
                        card={card}
                        onClick={() => clickHealthCard(card)}
                        onHover={() => hoverHealthCard(card)}
                    />
                ))}
            </div>
            {searchConsole === 'error' && (
                <LemonBanner type="warning" action={{ children: 'Try again', onClick: reloadHealth }}>
                    Couldn't load Google Search Console data for this page.
                </LemonBanner>
            )}
        </>
    )
}
