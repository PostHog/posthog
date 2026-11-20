import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function QuillReportNoteAddButton({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <Button
            size="sm"
            variant="link-muted"
            className="-mx-2 self-start"
            onClick={onClick}
            aria-label="Add a note about this report"
            data-attr="inbox-report-note-box"
        >
            <IconPlus />
            Add a note
        </Button>
    )
}
