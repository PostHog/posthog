import { IconChat, IconDocument, IconPlus, IconTarget } from '@posthog/icons'
import { Badge, Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

export interface QuillScoutNewMenuProps {
    creationDisabledReason: string | null
    chatDisabledReason: string | null | undefined
    onChat: () => void
    onForm: () => void
    onGoal?: () => void
}

export function QuillScoutNewMenu({
    creationDisabledReason,
    chatDisabledReason,
    onChat,
    onForm,
    onGoal,
}: QuillScoutNewMenuProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="primary" disabledReason={creationDisabledReason} data-attr="scout-new" />}
            >
                <IconPlus />
                New scout
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-w-80">
                <DropdownMenuItem
                    disabledReason={chatDisabledReason}
                    onClick={onChat}
                    data-attr="scout-new-chat"
                    description="Say what you want watched. The agent checks your data and builds the scout with you."
                >
                    <IconChat />
                    Chat with an agent
                    <Badge variant="success">Recommended</Badge>
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={onForm}
                    data-attr="scout-new-form"
                    description="You already know the instructions, schedule and where reports go."
                >
                    <IconDocument />
                    Fill in the form
                </DropdownMenuItem>
                {onGoal && (
                    <DropdownMenuItem
                        onClick={onGoal}
                        data-attr="scout-new-goal"
                        description="Say what you believe and the number that proves it. The scout finds ideas and tests the ones you choose."
                    >
                        <IconTarget />
                        Move a metric
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
