import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { TZLabel } from 'lib/components/TZLabel'
import { fullNameOrEmail } from 'lib/utils/strings'
import { priorityTone } from 'scenes/project-homepage/today/todayPriority'
import { userLogic } from 'scenes/userLogic'

import { SignalReport } from '../../types'
import { reportClaimant } from '../../utils/reportClaim'
import { reportFactStatus, reportOwnerKind, reportOwnerLabel } from '../../utils/reportFacts'

function Separator(): JSX.Element {
    return <span aria-hidden>·</span>
}

/** A report's read-only facts in one line: priority, status, owner, time. The list row and the triage card share it. */
export function QuillReportFacts({
    report,
    timestampField,
    className,
    children,
}: {
    report: SignalReport
    timestampField: 'created_at' | 'updated_at'
    className?: string
    children?: React.ReactNode
}): JSX.Element {
    const { user } = useValues(userLogic)
    const claimant = reportClaimant(report)
    const ownerKind = reportOwnerKind(report, user?.uuid ?? null)
    const owner =
        ownerKind === 'none' && report.is_suggested_reviewer
            ? 'Suggested for you'
            : reportOwnerLabel(ownerKind, claimant ? fullNameOrEmail(claimant) : null)

    return (
        <Text size="sm" variant="muted" render={<span />} className={className}>
            {children}
            {report.priority && (
                <>
                    <span className="TodayRow__label" data-tone={priorityTone(report.priority)}>
                        {report.priority}
                    </span>
                    <Separator />
                </>
            )}
            <span>{reportFactStatus(report)}</span>
            <Separator />
            <span>{owner}</span>
            <Separator />
            <span className="flex items-center gap-1 whitespace-nowrap">
                <span>{timestampField === 'created_at' ? 'Created' : 'Updated'}</span>
                <TZLabel time={report[timestampField]} />
            </span>
        </Text>
    )
}
