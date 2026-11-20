import { ReactNode, useState } from 'react'

import { Button } from '@posthog/quill'

import { ReportActivityEntry } from './reportActivityEntries'
import { ReportStageActivityRow } from './ReportStageActivityRow'
import { ReportStageSectionTitle } from './ReportStageSectionTitle'

const COLLAPSED_ENTRY_COUNT = 5

/** Notes and the work log, shared by every stage so the conversation stays in one place. */
export function ReportStageActivity({
    entries,
    notes,
    children,
}: {
    entries: ReportActivityEntry[]
    /** The notes people left, with the box to add one. */
    notes?: ReactNode
    /** The detail lines of the work log. */
    children?: ReactNode
}): JSX.Element {
    const [showAll, setShowAll] = useState(false)
    const shown = showAll ? entries : entries.slice(0, COLLAPSED_ENTRY_COUNT)
    const hiddenCount = entries.length - shown.length
    const firstNoteId = entries.find((entry) => entry.body)?.id

    return (
        <section
            className="flex flex-col gap-3 border-t border-border pt-6"
            aria-label="Activity"
            data-attr="inbox-report-activity"
        >
            <ReportStageSectionTitle>Activity</ReportStageSectionTitle>
            {notes}
            <ol className="m-0 flex list-none flex-col p-0">
                {shown.map((entry) => (
                    <ReportStageActivityRow key={entry.id} entry={entry} defaultOpen={entry.id === firstNoteId} />
                ))}
            </ol>
            {hiddenCount > 0 && (
                <Button
                    variant="link-muted"
                    size="sm"
                    className="-ms-2 self-start"
                    onClick={() => setShowAll(true)}
                    data-attr="inbox-report-activity-show-more"
                >
                    {`Show ${hiddenCount} more`}
                </Button>
            )}
            {children && <div className="-mx-2 flex flex-col">{children}</div>}
        </section>
    )
}
