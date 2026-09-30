import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent } from 'react'

import { IconSend } from '@posthog/icons'
import {
    Field,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupTextarea,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceTaskComposer({ id }: { id: string }): JSX.Element {
    const { taskDraft, creatingTask } = useValues(spaceSceneLogic({ id }))
    const { setTaskDraft, createTask } = useActions(spaceSceneLogic({ id }))
    const isEmpty = !taskDraft.trim()
    const submitLabel = creatingTask ? 'Sending' : isEmpty ? 'Enter a message' : 'Send message'

    return (
        <form
            onSubmit={(event) => {
                event.preventDefault()
                if (!isEmpty && !creatingTask) {
                    createTask()
                }
            }}
        >
            <Field>
                <InputGroup>
                    <InputGroupTextarea
                        aria-label="New session prompt"
                        placeholder="What do you want to ship?"
                        className="max-h-60 min-h-16"
                        value={taskDraft}
                        disabled={creatingTask}
                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setTaskDraft(event.target.value)}
                        onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                            // Enter sends and Shift+Enter adds a line, like the Desktop composer.
                            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                                event.preventDefault()
                                event.currentTarget.form?.requestSubmit()
                            }
                        }}
                        data-attr="today-space-new-task-input"
                    />
                    <InputGroupAddon align="block-end">
                        <Tooltip>
                            <TooltipTrigger
                                delay={0}
                                render={
                                    <InputGroupButton
                                        type="submit"
                                        variant="primary"
                                        size="icon-sm"
                                        className="ml-auto"
                                        aria-label="Send message"
                                        disabled={isEmpty}
                                        loading={creatingTask}
                                        data-attr="today-space-new-task-submit"
                                    />
                                }
                            >
                                <IconSend />
                            </TooltipTrigger>
                            <TooltipContent>{submitLabel}</TooltipContent>
                        </Tooltip>
                    </InputGroupAddon>
                </InputGroup>
            </Field>
        </form>
    )
}
