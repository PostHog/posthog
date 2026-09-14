import { LemonDivider } from '@posthog/lemon-ui'

import { PropertiesTable } from '../PropertiesTable'
import type { PropertyTableRow } from '../PropertiesTable'

export interface ExceptionPropertySection {
    id: string
    title: string
    entries: ([string, unknown] | PropertyTableRow)[]
}

export interface ExceptionPropertiesTableProps {
    sections: ExceptionPropertySection[]
    emptyMessage?: string
    onFilterValue?: (key: string, value: string | number | boolean) => void
}

export function ExceptionPropertiesTable({
    sections,
    emptyMessage = 'No properties',
    onFilterValue,
}: ExceptionPropertiesTableProps): JSX.Element {
    const populatedSections = sections
        .map((section) => ({
            ...section,
            entries: section.entries.filter(hasValue),
        }))
        .filter((section) => section.entries.length > 0)

    if (populatedSections.length === 0) {
        return <div className="flex h-32 items-center justify-center text-sm text-secondary">{emptyMessage}</div>
    }

    return (
        <div className="pb-6">
            {populatedSections.map((section) => (
                <section key={section.id} aria-labelledby={section.id}>
                    <div className="flex h-8 items-center gap-3 px-2.5">
                        <LemonDivider className="my-0 flex-1" />
                        <h3
                            id={section.id}
                            className="m-0 shrink-0 text-xs font-semibold uppercase tracking-wide text-secondary"
                        >
                            {section.title}
                        </h3>
                        <LemonDivider className="my-0 flex-1" />
                    </div>
                    <PropertiesTable
                        entries={section.entries}
                        firstColumnWidth="12rem"
                        tableLayout="fixed"
                        onFilterValue={onFilterValue}
                    />
                </section>
            ))}
        </div>
    )
}

function hasValue(entry: [string, unknown] | PropertyTableRow): boolean {
    return (Array.isArray(entry) ? entry[1] : entry.value) !== undefined
}
