import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function QuillReportNoteAddButton({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <Button
            size="sm"
            variant="link-muted"
            className="QuillReportNoteAdd -mx-2 self-start"
            onClick={onClick}
            aria-label="Add a note about this report"
            data-attr="inbox-report-note-box"
        >
            <span className="QuillReportNoteAdd__plus" aria-hidden>
                <IconPlus />
            </span>
            Add a note
        </Button>
    )
}
