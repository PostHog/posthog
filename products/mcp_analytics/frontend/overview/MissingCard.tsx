import { useValues } from 'kea'

import { Badge, Card, CardContent, CardHeader, CardTitle } from '@posthog/quill-primitives'

import { Link } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import { formatNumber } from '../dashboard/formatters'
import { mcpOverviewLogic } from './mcpOverviewLogic'

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted">{title}</span>
            {children}
        </div>
    )
}

function UnknownToolsSection(): JSX.Element {
    const { unknownToolSessions } = useValues(mcpOverviewLogic)

    return (
        <Section title="Tools that do not exist">
            {unknownToolSessions === 0 ? (
                <span className="text-sm text-muted">No agent asked for a tool you do not have.</span>
            ) : (
                <>
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-sm italic text-muted">Names not captured yet</span>
                        <Badge variant="warning" translate="no">
                            {formatNumber(unknownToolSessions)} sessions
                        </Badge>
                    </div>
                    <p className="m-0 text-sm text-muted">
                        Your server records the rejection but not the name the agent asked for. Capture it to fill this
                        list.
                    </p>
                </>
            )}
        </Section>
    )
}

function ReportedSection(): JSX.Element {
    const { missingReports, rangeLabel } = useValues(mcpOverviewLogic)
    const newest = missingReports[0]

    return (
        <Section title="Reported through get_more_tools">
            {!newest ? (
                <span className="text-sm text-muted">No reports in {rangeLabel.toLowerCase()}.</span>
            ) : (
                <>
                    <p className="m-0 text-sm italic text-muted">{newest.intent}</p>
                    <Link to={urls.mcpAnalyticsMissingCapabilities()} className="text-sm">
                        Read every report
                    </Link>
                </>
            )}
        </Section>
    )
}

/** What agents wanted from the server and could not get, in their own words. */
export function MissingCard(): JSX.Element {
    return (
        <Card size="sm" className="gap-0">
            <CardHeader className="border-b border-border pb-3">
                <CardTitle>What they asked for that you do not have</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 pt-3">
                <UnknownToolsSection />
                <ReportedSection />
            </CardContent>
        </Card>
    )
}
