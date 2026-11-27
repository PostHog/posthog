import { IconExternal } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

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
    const externalUrl =
        lookup.kind === 'domain' ? `https://${lookup.value}` : lookup.kind === 'url' ? lookup.value : null
    if (!externalUrl || !isWebUrl(externalUrl)) {
        return null
    }
    const openLabel = lookup.kind === 'url' ? 'Open page' : 'Open site'
    const pageReportTooltip = "See this page's traffic, including visits from AI assistants"

    return (
        <div className="flex flex-wrap items-center gap-2">
            {lookup.kind === 'url' ? (
                <Text size="sm" weight="semibold" render={<span className="m-0 min-w-0 break-all" />}>
                    {lookup.value}
                </Text>
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
