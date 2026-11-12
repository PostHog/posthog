import { useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    IconStack,
    IconStackItem,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { fullNameOrEmail } from 'lib/utils/strings'
import { priorityTone } from 'scenes/project-homepage/today/todayPriority'
import { reportIcon } from 'scenes/project-homepage/today/todayRowIcons'
import { reportSourceLine } from 'scenes/project-homepage/today/todaySignalReports'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import type { _UserApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport } from '../../types'
import { reportStatusLabel } from '../badges/SignalReportStatusBadge'
import { ReportDetailAction } from './ReportDetailActions'

const INLINE_ACTION_LIMIT = 2

export function QuillReportFactLine({
    report,
    claimant,
    isClaimedByMe,
    actions,
}: {
    report: SignalReport
    claimant: _UserApi | null
    isClaimedByMe: boolean
    actions: ReportDetailAction[]
}): JSX.Element {
    const { phoneLayout } = useValues(todayShellLogic)
    const sources = reportSourceLine(report)
    const icon = reportIcon(report)
    const inlineActions = phoneLayout ? [] : actions.slice(0, INLINE_ACTION_LIMIT)
    const menuActions = phoneLayout ? actions : actions.slice(INLINE_ACTION_LIMIT)
    const separator = (
        <span aria-hidden className="-mx-0.5">
            ·
        </span>
    )

    return (
        <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <Text
                size="xs"
                variant="muted"
                render={<div />}
                className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 whitespace-nowrap"
            >
                <IconStack className="TodayReportHeader__icon" title={sources.title || sources.line}>
                    <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
                </IconStack>
                {report.priority && (
                    <>
                        <span className="TodayRow__label" data-tone={priorityTone(report.priority)}>
                            {report.priority}
                        </span>
                        {separator}
                    </>
                )}
                <span>{reportStatusLabel(report.status, report.suppression_source)}</span>
                {claimant && (
                    <>
                        {separator}
                        <span data-attr="inbox-report-claim-pill">
                            {isClaimedByMe ? 'Claimed by you' : `Claimed by ${fullNameOrEmail(claimant)}`}
                        </span>
                    </>
                )}
                {separator}
                <span className="flex items-center gap-1">
                    {!phoneLayout && <span>Updated</span>}
                    <TZLabel time={report.updated_at} />
                </span>
            </Text>
            {actions.length > 0 && (
                <div className="-mx-2 flex shrink-0 items-center gap-0.5">
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
                            {action.icon}
                            {action.label}
                        </Button>
                    ))}
                    {menuActions.length > 0 && (
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
            )}
        </div>
    )
}
