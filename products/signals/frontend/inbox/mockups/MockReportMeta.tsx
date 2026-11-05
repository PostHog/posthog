import type { ReactNode } from 'react'

import { IconStack, IconStackItem, Text } from '@posthog/quill'

import { priorityTone } from 'scenes/project-homepage/today/todayPriority'
import { reportIcon } from 'scenes/project-homepage/today/todayRowIcons'

import type { MockReport } from './mockupData'

export function MockReportMeta({ report, actions }: { report: MockReport; actions?: ReactNode }): JSX.Element {
    const icon = reportIcon({ source_products: [report.source] })
    return (
        <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <Text
                size="xs"
                variant="muted"
                render={<div />}
                className="flex min-w-0 items-center gap-2 whitespace-nowrap"
            >
                <IconStack className="TodayReportHeader__icon" title={report.sources}>
                    <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
                </IconStack>
                <span className="TodayRow__label" data-tone={priorityTone(report.priority)}>
                    {report.priority}
                </span>
                <span aria-hidden className="-mx-0.5">
                    ·
                </span>
                <span className="truncate">Updated {report.updated}</span>
            </Text>
            {actions && <div className="-mx-2 flex shrink-0 items-center gap-0.5">{actions}</div>}
        </div>
    )
}
