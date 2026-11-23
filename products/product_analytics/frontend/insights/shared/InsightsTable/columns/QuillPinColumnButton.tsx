import { IconPin, IconPinFilled } from '@posthog/icons'
import { Button } from '@posthog/quill'

interface QuillPinColumnButtonProps {
    isPinned: boolean
    onTogglePin: () => void
}

export function QuillPinColumnButton({ isPinned, onTogglePin }: QuillPinColumnButtonProps): JSX.Element {
    const label = isPinned ? 'Unpin column' : 'Pin column'
    return (
        <Button
            size="icon-sm"
            className="ml-2 align-middle"
            aria-label={label}
            tooltip={label}
            aria-pressed={isPinned}
            onClick={onTogglePin}
        >
            {isPinned ? <IconPinFilled /> : <IconPin />}
        </Button>
    )
}
