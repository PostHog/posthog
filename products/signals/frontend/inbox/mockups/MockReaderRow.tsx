import { IconStack, IconStackItem } from '@posthog/quill'

import { priorityTone } from 'scenes/project-homepage/today/todayPriority'
import { reportIcon } from 'scenes/project-homepage/today/todayRowIcons'

import type { MockReport } from './mockupData'
import { rowFacts } from './mockupFormat'

/** A `TodayRow` look-alike that selects the report instead of opening a page. */
export function MockReaderRow({
    report,
    selected,
    onSelect,
}: {
    report: MockReport
    selected: boolean
    onSelect: () => void
}): JSX.Element {
    const icon = reportIcon({ source_products: [report.source] })
    return (
        <li className="TodayRow" data-interactive data-expanded={selected || undefined}>
            <IconStack className="TodayRow__icons">
                <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
            </IconStack>
            <div className="min-w-0">
                <button
                    type="button"
                    className="TodayRow__title TodayRow__link TodayRow__toggle"
                    aria-current={selected || undefined}
                    onClick={onSelect}
                >
                    {report.title}
                </button>
                <p className="TodayRow__meta">
                    <span className="TodayRow__label" data-tone={priorityTone(report.priority)}>
                        {report.priority}
                    </span>
                    {rowFacts(report).map((fact) => (
                        <span key={fact}>{` · ${fact}`}</span>
                    ))}
                </p>
            </div>
        </li>
    )
}
