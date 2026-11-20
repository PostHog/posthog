import { Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { priorityTone } from 'scenes/project-homepage/today/todayPriority'

import { SignalReport, SignalReportPriority } from '../../types'
import { reportFactStatus } from '../../utils/reportFacts'
import { QuillReportFactActions } from './QuillReportFactActions'
import { QuillReportOwner } from './QuillReportOwner'
import { QuillReportPriorityMenu } from './QuillReportPriorityMenu'
import { QuillReportSourceIcons } from './QuillReportSourceIcons'
import { QuillReportStatusMenu } from './QuillReportStatusMenu'
import { ReportDetailAction } from './ReportDetailActions'
import { QuillReportClaim } from './useQuillReportClaim'

const STATUS_ACTION_KEYS = ['resolve', 'dismiss', 'reopen', 'restore']

function Separator(): JSX.Element {
    return <span aria-hidden>·</span>
}

export function QuillReportFactLine({
    report,
    claim,
    actions,
    prioritySaving,
    onPriorityChange,
}: {
    report: SignalReport
    claim: QuillReportClaim
    actions: ReportDetailAction[]
    prioritySaving: boolean
    onPriorityChange: (priority: SignalReportPriority) => void
}): JSX.Element {
    const statusActions = actions.filter((action) => STATUS_ACTION_KEYS.includes(action.key))
    const created = report.created_at === report.updated_at

    return (
        <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <Text
                size="sm"
                variant="muted"
                render={<div />}
                className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-1"
            >
                <QuillReportSourceIcons report={report} className="TodayReportHeader__icon me-1" />
                {report.priority && (
                    <>
                        {report.status === 'suppressed' || report.status === 'resolved' ? (
                            <span className="TodayRow__label" data-tone={priorityTone(report.priority)}>
                                {report.priority}
                            </span>
                        ) : (
                            <QuillReportPriorityMenu
                                priority={report.priority}
                                saving={prioritySaving}
                                onChange={onPriorityChange}
                            />
                        )}
                        <Separator />
                    </>
                )}
                <QuillReportStatusMenu label={reportFactStatus(report)} actions={statusActions} />
                <Separator />
                <QuillReportOwner claim={claim} />
                <Separator />
                <span className="flex items-center gap-1 whitespace-nowrap">
                    <span>{created ? 'Created' : 'Updated'}</span>
                    <TZLabel time={report.updated_at} />
                </span>
            </Text>
            <QuillReportFactActions claim={claim} actions={actions} />
        </div>
    )
}
