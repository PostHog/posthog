import { useActions, useValues } from 'kea'
import { KeyboardEvent } from 'react'

import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Field,
    FieldLabel,
    Text,
    Textarea,
} from '@posthog/quill'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'

interface QuillEditWithAgentPromptProps extends MessageTemplateLogicProps {
    sentenceRef: React.RefObject<HTMLTextAreaElement>
}

export function QuillEditWithAgentPrompt({ sentenceRef, ...props }: QuillEditWithAgentPromptProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { changeSentence, agentPrompt, copyAgentPromptDisabledReason } = useValues(logic)
    const { setChangeSentence, copyAgentPrompt } = useActions(logic)

    const copyOnCmdEnter = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
            event.preventDefault()
            copyAgentPrompt()
        }
    }

    return (
        <>
            <Field>
                <FieldLabel htmlFor="message-template-change-sentence">Describe the change</FieldLabel>
                <Textarea
                    id="message-template-change-sentence"
                    ref={sentenceRef}
                    value={changeSentence}
                    onChange={(event) => setChangeSentence(event.target.value)}
                    onKeyDown={copyOnCmdEnter}
                    rows={3}
                    data-attr="message-template-change-sentence"
                />
            </Field>
            <div className="flex justify-end">
                <Button
                    variant="primary"
                    data-attr="message-template-copy-agent-prompt"
                    onClick={copyAgentPrompt}
                    disabledReason={copyAgentPromptDisabledReason}
                >
                    Copy prompt
                </Button>
            </div>
            <Collapsible>
                <CollapsibleTrigger>Show full prompt</CollapsibleTrigger>
                <CollapsibleContent>
                    <Text
                        size="xs"
                        render={<div />}
                        className="m-0 whitespace-pre-wrap break-words font-mono"
                        data-attr="message-template-agent-prompt"
                    >
                        {agentPrompt}
                    </Text>
                </CollapsibleContent>
            </Collapsible>
        </>
    )
}
