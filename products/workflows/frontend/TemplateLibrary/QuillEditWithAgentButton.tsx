import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'
import { QuillEditWithAgentPrompt } from './QuillEditWithAgentPrompt'

export function QuillEditWithAgentButton(props: MessageTemplateLogicProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { agentPromptOpen, templateLoading } = useValues(logic)
    const { setAgentPromptOpen } = useActions(logic)
    const loadingReason = templateLoading ? 'Wait for the template to load' : undefined
    const sentenceRef = useRef<HTMLTextAreaElement>(null)

    return (
        <Popover open={agentPromptOpen} onOpenChange={setAgentPromptOpen}>
            <PopoverTrigger
                render={
                    <Button
                        variant="primary"
                        data-attr="message-template-edit-with-agent"
                        disabledReason={loadingReason}
                    />
                }
            >
                Edit with your agent
            </PopoverTrigger>
            <PopoverContent
                align="end"
                className="w-96 max-w-full"
                aria-label="Edit with your agent"
                initialFocus={() => focusAtEnd(sentenceRef.current)}
            >
                <QuillEditWithAgentPrompt {...props} sentenceRef={sentenceRef} />
            </PopoverContent>
        </Popover>
    )
}

function focusAtEnd(field: HTMLTextAreaElement | null): HTMLTextAreaElement | null {
    field?.setSelectionRange(field.value.length, field.value.length)
    return field
}
