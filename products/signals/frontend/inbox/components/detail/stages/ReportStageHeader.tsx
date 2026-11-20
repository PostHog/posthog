import { Badge, Dot, Heading, IconStack, IconStackItem, Text } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { TZLabel } from 'lib/components/TZLabel'

import { SignalReport, SignalReportStatus } from '../../../types'
import { displayConventionalCommitTitle } from '../../../utils/reportPresentation'
import { STATUS_LABELS } from '../../badges/SignalReportStatusBadge'
import { knownSourceProductEntries } from '../../badges/sourceProductIcons'

type BadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success' | 'completed'

const STATUS_BADGE_VARIANT: Partial<Record<SignalReportStatus, BadgeVariant>> = {
    [SignalReportStatus.READY]: 'success',
    [SignalReportStatus.PENDING_INPUT]: 'warning',
    [SignalReportStatus.MONITORING]: 'info',
    [SignalReportStatus.RESOLVED]: 'completed',
    [SignalReportStatus.FAILED]: 'destructive',
}

const SOURCE_PRODUCT_COLOR: Record<string, string> = {
    error_tracking: 'var(--color-product-error-tracking-light)',
    session_replay: 'var(--color-product-session-replay-light)',
    llm_analytics: 'var(--color-product-llm-analytics-light)',
    logs: 'var(--color-product-logs-light)',
}

function ownerLine(report: SignalReport, isClaimedByMe: boolean): string {
    if (isClaimedByMe) {
        return 'Claimed by you'
    }
    const owner = report.assignee?.responsible_user ?? report.assignee?.user
    return owner ? `Claimed by ${owner.first_name}` : 'Unclaimed'
}

export function ReportStageHeader({
    report,
    isClaimedByMe,
}: {
    report: SignalReport
    isClaimedByMe: boolean
}): JSX.Element {
    const owner = report.assignee?.responsible_user ?? report.assignee?.user
    const sources = knownSourceProductEntries(report.source_products)
    const urgent = report.priority === 'P0' || report.priority === 'P1'

    return (
        <header className="flex flex-col gap-3">
            <Heading size="xl" render={<h1 className="m-0" />} className="leading-snug text-balance">
                {displayConventionalCommitTitle(report.title, 'Untitled report')}
            </Heading>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <Text
                    size="xs"
                    variant="muted"
                    render={<div />}
                    className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5"
                >
                    <Badge variant={STATUS_BADGE_VARIANT[report.status] ?? 'default'}>
                        {report.status === SignalReportStatus.MONITORING && <Dot variant="info" pulse aria-hidden />}
                        {STATUS_LABELS[report.status] ?? report.status}
                    </Badge>
                    <span className="flex items-center gap-1.5">
                        {owner && (
                            <QuillPersonAvatar
                                name={`${owner.first_name} ${owner.last_name}`}
                                email={owner.email}
                                size="xs"
                            />
                        )}
                        <span className={owner ? 'text-foreground' : undefined}>
                            {ownerLine(report, isClaimedByMe)}
                        </span>
                    </span>
                    {report.priority && (
                        <span className={urgent ? 'font-medium text-destructive-foreground' : 'text-foreground'}>
                            {report.priority}
                        </span>
                    )}
                    {sources.length > 0 && (
                        <span className="flex items-center gap-1.5">
                            <IconStack>
                                {sources.map(({ key, meta }) => (
                                    <IconStackItem key={key} color={SOURCE_PRODUCT_COLOR[key]}>
                                        <meta.Icon />
                                    </IconStackItem>
                                ))}
                            </IconStack>
                            <span>{sources.map(({ meta }) => meta.label).join(', ')}</span>
                        </span>
                    )}
                </Text>
                <Text size="xs" variant="muted" render={<div />} className="flex items-center gap-1 whitespace-nowrap">
                    <span>Discovered</span>
                    <TZLabel time={report.created_at} />
                    <span aria-hidden>·</span>
                    <span>Updated</span>
                    <TZLabel time={report.updated_at} />
                </Text>
            </div>
        </header>
    )
}
