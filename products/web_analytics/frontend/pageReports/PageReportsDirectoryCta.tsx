import { useActions } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { pageReportsLogic } from 'scenes/web-analytics/pageReportsLogic'

export function PageReportsDirectoryCta(): JSX.Element {
    const { trackDirectoryCtaClicked } = useActions(pageReportsLogic)

    return (
        <div
            className="border rounded bg-surface-primary px-4 py-3 flex flex-wrap items-center justify-between gap-3"
            data-attr="search-and-ai-page-reports-cta"
        >
            <div className="flex flex-col min-w-0">
                <span className="font-semibold">Every page, ranked by search and AI traffic</span>
                <span className="text-sm text-secondary">
                    Page reports lists all your pages with Google search, AI referrals and AI crawls. Open any page for
                    its keywords, crawlers and health.
                </span>
            </div>
            <LemonButton
                type="secondary"
                size="small"
                to={urls.webAnalyticsPageReports()}
                sideIcon={<IconArrowRight />}
                onClick={trackDirectoryCtaClicked}
                data-attr="search-and-ai-open-page-reports"
            >
                Open page reports
            </LemonButton>
        </div>
    )
}
