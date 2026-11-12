import { IconStack, IconStackItem } from '@posthog/quill'

import { sourceIcon } from 'scenes/project-homepage/today/todayRowIcons'
import { reportSourceLine } from 'scenes/project-homepage/today/todaySignalReports'

import { SignalReport } from '../../types'

const MAX_ICONS = 3

export function QuillReportSourceIcons({
    report,
    className,
}: {
    report: Pick<SignalReport, 'source_products' | 'scout_name'>
    className?: string
}): JSX.Element {
    const sources = reportSourceLine(report)
    const products = report.source_products?.length ? report.source_products : [undefined]
    const icons = [...new Set(products)].slice(0, MAX_ICONS).map(sourceIcon)
    return (
        <IconStack className={className} title={sources.title || sources.line}>
            {icons.map((icon, index) => (
                <IconStackItem key={index} color={icon.color}>
                    {icon.glyph}
                </IconStackItem>
            ))}
        </IconStack>
    )
}
