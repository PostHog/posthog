import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const externalUrl =
        lookup.kind === 'domain' ? `https://${lookup.value}` : lookup.kind === 'url' ? lookup.value : null
    if (!externalUrl || !isWebUrl(externalUrl)) {
        return null
    }
    const openLabel = lookup.kind === 'url' ? 'Open page' : 'Open site'
    const pageReportTooltip = "See this page's traffic, including visits from AI assistants"

    if (todayRailNav) {
        return (
            <div className="flex flex-wrap items-center gap-2">
                {lookup.kind === 'url' ? (
                    <span className="min-w-0 break-all text-sm font-semibold">{lookup.value}</span>
                ) : null}
                <Button
                    variant="outline"
                    nativeButton={false}
                    render={<LinkPrimitive to={externalUrl} target="_blank" />}
                    data-attr="content-autopilot-citations-open-site"
                >
                    {openLabel}
                    <IconExternal />
                </Button>
                {isOwnPage ? (
                    <Button
                        variant="outline"
                        nativeButton={false}
                        render={<LinkPrimitive to={pageReportPath(lookup.value)} />}
                        tooltip={pageReportTooltip}
                        data-attr="content-autopilot-citations-page-report"
                    >
                        Page report
                    </Button>
                ) : null}
            </div>
        )
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
                {openLabel}
            </LemonButton>
            {isOwnPage ? (
                <LemonButton
                    size="small"
                    type="secondary"
                    to={pageReportPath(lookup.value)}
                    tooltip={pageReportTooltip}
                    data-attr="content-autopilot-citations-page-report"
                >
                    Page report
                </LemonButton>
            ) : null}
        </div>
    )
}
