import { IconStack, IconStackItem } from '@posthog/quill'

import { reportIcons } from 'scenes/project-homepage/today/todayRowIcons'
import { reportSourceLine } from 'scenes/project-homepage/today/todaySignalReports'

import { SignalReport } from '../../types'

export function QuillReportSourceIcons({
    report,
    className,
}: {
    report: Pick<SignalReport, 'source_products' | 'scout_name'>
    className?: string
}): JSX.Element {
    const sources = reportSourceLine(report)
    return (
        <IconStack className={className} title={sources.title || sources.line}>
            {reportIcons(report).map((icon, index) => (
                <IconStackItem key={index} color={icon.color}>
                    {icon.glyph}
                </IconStackItem>
            ))}
        </IconStack>
    )
}
