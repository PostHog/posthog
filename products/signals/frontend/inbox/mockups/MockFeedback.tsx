import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

export function MockFeedback(): JSX.Element {
    return (
        <footer className="flex flex-wrap items-center gap-1">
            <Text size="xs" variant="muted" render={<span />} className="me-1">
                Was this report useful?
            </Text>
            <Button size="icon-sm" aria-label="This report was useful" tooltip="Yes, this was useful">
                <IconThumbsUp />
            </Button>
            <Button size="icon-sm" aria-label="This report was not useful" tooltip="No, this wasn't useful">
                <IconThumbsDown />
            </Button>
        </footer>
    )
}
