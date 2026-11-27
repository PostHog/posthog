import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

export const AiVisibilityTableExpandButton = ({
    expanded,
    onToggle,
}: {
    expanded: boolean
    onToggle: () => void
}): JSX.Element => (
    <Button
        size="icon-sm"
        aria-label={expanded ? 'Collapse row' : 'Expand row'}
        aria-expanded={expanded}
        onClick={(event) => {
            event.stopPropagation()
            onToggle()
        }}
    >
        {expanded ? <IconChevronDown /> : <IconChevronRight />}
    </Button>
)
