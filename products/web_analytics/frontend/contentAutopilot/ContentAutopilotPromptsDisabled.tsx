import { IconLock } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

export const ContentAutopilotPromptsDisabled = (): JSX.Element => (
    <Empty>
        <EmptyHeader>
            <EmptyMedia variant="icon">
                <IconLock />
            </EmptyMedia>
            <EmptyTitle>Prompt tracking is not turned on</EmptyTitle>
            <EmptyDescription>
                This project doesn't have access to prompt tracking yet. Ask PostHog support to turn it on.
            </EmptyDescription>
        </EmptyHeader>
    </Empty>
)
