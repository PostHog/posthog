import { LemonButton } from '@posthog/lemon-ui'

import { pageReportPath } from '../pageReports/pageReportsUtils'
import type { CitationsLookup } from './contentAutopilotCitationsModalLogic'

// Engine output is third-party text: only plain http(s) URLs become links.
const isWebUrl = (url: string): boolean => /^https?:\/\//i.test(url)

/** Links out of the citations modal: the page or site itself, and the page report for one of your own pages. */
export const ContentAutopilotCitationsActions = ({
    lookup,
    isOwnPage,
}: {
    lookup: CitationsLookup
    isOwnPage: boolean
}): JSX.Element | null => {
    const externalUrl =
        lookup.kind === 'domain' ? `https://${lookup.value}` : lookup.kind === 'url' ? lookup.value : null
    if (!externalUrl || !isWebUrl(externalUrl)) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-2">
            {lookup.kind === 'url' ? (
                <span className="min-w-0 break-all text-sm font-semibold">{lookup.value}</span>
            ) : null}
            <LemonButton
                size="small"
                type="secondary"
                to={externalUrl}
                targetBlank
                data-attr="content-autopilot-citations-open-site"
            >
                {lookup.kind === 'url' ? 'Open page' : 'Open site'}
            </LemonButton>
            {isOwnPage ? (
                <LemonButton
                    size="small"
                    type="secondary"
                    to={pageReportPath(lookup.value)}
                    tooltip="See this page's traffic, including visits from AI assistants"
                    data-attr="content-autopilot-citations-page-report"
                >
                    Page report
                </LemonButton>
            ) : null}
        </div>
    )
}
