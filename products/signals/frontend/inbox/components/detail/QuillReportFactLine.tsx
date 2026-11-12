import { useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { priorityTone } from 'scenes/project-homepage/today/todayPriority'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { SignalReport, SignalReportPriority } from '../../types'
import { reportFactStatus } from '../../utils/reportFacts'
import { QuillReportOwner } from './QuillReportOwner'
import { QuillReportPriorityMenu } from './QuillReportPriorityMenu'
import { QuillReportSourceIcons } from './QuillReportSourceIcons'
import { QuillReportStatusMenu } from './QuillReportStatusMenu'
import { ReportDetailAction } from './ReportDetailActions'
import { QuillReportClaim } from './useQuillReportClaim'

const INLINE_ACTION_LIMIT = 2
// The owner in the fact line holds the take-over action, so the action list does not repeat it.
const OWNER_ACTION_KEYS = ['takeover']
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
    const { phoneLayout } = useValues(todayShellLogic)
    const listed = actions.filter((action) => !OWNER_ACTION_KEYS.includes(action.key))
    const inlineActions = phoneLayout ? [] : listed.slice(0, INLINE_ACTION_LIMIT)
    const menuActions = phoneLayout ? listed : listed.slice(INLINE_ACTION_LIMIT)
    const statusActions = actions.filter((action) => STATUS_ACTION_KEYS.includes(action.key))
    // A phone has no room for the Claim button, so the claim actions join the other actions in the menu.
    const claimMenuItems = phoneLayout
        ? [
              claim.canClaim && { key: 'claim', label: 'Claim', onClick: claim.claim },
              claim.canUnclaim && { key: 'unclaim', label: 'Unclaim', onClick: claim.unclaim },
              claim.canTakeOver && { key: 'takeover', label: 'Take over', onClick: claim.takeOver },
          ].filter((item) => !!item)
        : []
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
            <div className="-mx-2 flex shrink-0 items-center gap-0.5 self-start">
                {!phoneLayout && claim.canClaim && (
                    <Button
                        size="sm"
                        variant="link-muted"
                        loading={claim.saving}
                        onClick={claim.claim}
                        tooltip="Claim this report (U)"
                        data-attr="inbox-report-claim"
                    >
                        Claim
                    </Button>
                )}
                {inlineActions.map((action) => (
                    <Button
                        key={action.key}
                        size="sm"
                        variant={action.primary ? 'outline' : 'link-muted'}
                        loading={action.loading}
                        // A disabled action explains only why it is unavailable, not what it would do.
                        tooltip={action.disabledReason ? undefined : action.tooltip}
                        disabledReason={action.disabledReason}
                        onClick={action.onClick}
                        data-attr={`inbox-report-action-${action.key}`}
                    >
                        {action.label}
                    </Button>
                ))}
                {menuActions.length + claimMenuItems.length > 0 && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-sm"
                                    variant="link-muted"
                                    aria-label="More actions"
                                    tooltip="More actions"
                                    data-attr="inbox-report-more-actions"
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {claimMenuItems.map((item) => (
                                <DropdownMenuItem
                                    key={item.key}
                                    disabledReason={claim.saving ? 'Working…' : undefined}
                                    onClick={item.onClick}
                                    data-attr={`inbox-report-action-${item.key}`}
                                >
                                    {item.label}
                                </DropdownMenuItem>
                            ))}
                            {menuActions.map((action) => (
                                <DropdownMenuItem
                                    key={action.key}
                                    disabledReason={action.loading ? 'Working…' : action.disabledReason}
                                    onClick={action.onClick}
                                    data-attr={`inbox-report-action-${action.key}`}
                                >
                                    {action.icon}
                                    {action.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </div>
        </div>
    )
}
