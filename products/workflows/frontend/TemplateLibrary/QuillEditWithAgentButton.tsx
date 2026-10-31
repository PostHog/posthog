import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronDown, IconCopy } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    ButtonGroupSeparator,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@posthog/quill'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'
import { QuillEditWithAgentPrompt } from './QuillEditWithAgentPrompt'

export function QuillEditWithAgentButton(props: MessageTemplateLogicProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { agentPromptOpen, templateLoading } = useValues(logic)
    const { setAgentPromptOpen, copyHtmlFile } = useActions(logic)
    const loadingReason = templateLoading ? 'Wait for the template to load' : undefined
    const sentenceRef = useRef<HTMLTextAreaElement>(null)

    return (
        <ButtonGroup>
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
            <ButtonGroupSeparator />
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="primary"
                            size="icon"
                            aria-label="More ways to copy this template"
                            tooltip="More ways to copy this template"
                            disabledReason={loadingReason}
                            data-attr="message-template-copy-options"
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuItem data-attr="message-template-copy-html-file" onClick={copyHtmlFile}>
                        <IconCopy />
                        Copy HTML file
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    )
}

function focusAtEnd(field: HTMLTextAreaElement | null): HTMLTextAreaElement | null {
    field?.setSelectionRange(field.value.length, field.value.length)
    return field
}
