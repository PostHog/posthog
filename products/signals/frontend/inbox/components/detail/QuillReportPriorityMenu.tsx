import './QuillReportDetail.scss'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { priorityTone } from 'scenes/project-homepage/today/todayPriority'

import { INBOX_PRIORITY_OPTIONS } from '../../filterOptions'
import { SignalReportPriority } from '../../types'

export function QuillReportPriorityMenu({
    priority,
    saving,
    onChange,
}: {
    priority: SignalReportPriority
    saving: boolean
    onChange: (priority: SignalReportPriority) => void
}): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="inline"
                        variant="link-muted"
                        className="QuillReportFact TodayRow__label"
                        data-tone={priorityTone(priority)}
                        loading={saving}
                        aria-label={`Priority ${priority}. Change the priority`}
                        tooltip="Change the priority"
                        data-attr="inbox-report-priority"
                    />
                }
            >
                {priority}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup
                    value={priority}
                    onValueChange={(value: string) => onChange(value as SignalReportPriority)}
                >
                    {INBOX_PRIORITY_OPTIONS.map((option) => (
                        <DropdownMenuRadioItem
                            key={option}
                            value={option}
                            data-attr={`inbox-report-priority-${option}`}
                        >
                            {option}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
