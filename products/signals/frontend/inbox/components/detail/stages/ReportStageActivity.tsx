import { useState } from 'react'

import { IconSend } from '@posthog/icons'
import { Button, InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@posthog/quill'

import { ReportActivityEntry } from './reportActivityEntries'
import { ReportStageActivityRow } from './ReportStageActivityRow'
import { ReportStageSectionTitle } from './ReportStageSectionTitle'

const COLLAPSED_ENTRY_COUNT = 5

/** Comments and the work log, shared by every stage so the conversation stays in one place. */
export function ReportStageActivity({
    entries,
    onComment,
}: {
    entries: ReportActivityEntry[]
    onComment: (comment: string) => void
}): JSX.Element {
    const [showAll, setShowAll] = useState(false)
    const [draft, setDraft] = useState('')
    const shown = showAll ? entries : entries.slice(0, COLLAPSED_ENTRY_COUNT)
    const hiddenCount = entries.length - shown.length
    const firstNoteId = entries.find((entry) => entry.body)?.id
    const comment = draft.trim()

    return (
        <section
            className="flex flex-col gap-3 border-t border-border pt-6"
            aria-label="Activity"
            data-attr="inbox-report-activity"
        >
            <ReportStageSectionTitle>Activity</ReportStageSectionTitle>
            <form
                onSubmit={(event) => {
                    event.preventDefault()
                    if (comment) {
                        onComment(comment)
                        setDraft('')
                    }
                }}
            >
                <InputGroup>
                    <InputGroupInput
                        aria-label="Comment"
                        placeholder="Leave a comment"
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        data-attr="inbox-report-comment-input"
                    />
                    <InputGroupAddon align="inline-end">
                        <InputGroupButton
                            type="submit"
                            size="icon-xs"
                            aria-label="Send comment"
                            disabledReason={comment ? null : 'Write a comment first'}
                            data-attr="inbox-report-comment-send"
                        >
                            <IconSend />
                        </InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>
            </form>
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
        </section>
    )
}
