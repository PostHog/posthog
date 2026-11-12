import './QuillReportDetail.scss'

import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { ReportDetailAction } from './ReportDetailActions'

export function QuillReportStatusMenu({
    label,
    actions,
}: {
    label: string
    actions: ReportDetailAction[]
}): JSX.Element {
    if (actions.length === 0) {
        return <span data-attr="inbox-report-status">{label}</span>
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="inline"
                        variant="link-muted"
                        className="QuillReportFact"
                        aria-label={`Status: ${label}. Change the status`}
                        tooltip="Change the status"
                        data-attr="inbox-report-status"
                    />
                }
            >
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {actions.map((action) => (
                    <DropdownMenuItem
                        key={action.key}
                        disabledReason={action.loading ? 'Working…' : action.disabledReason}
                        onClick={action.onClick}
                        data-attr={`inbox-report-status-${action.key}`}
                    >
                        {action.icon}
                        {action.label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
