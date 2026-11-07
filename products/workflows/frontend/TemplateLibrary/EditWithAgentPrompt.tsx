import { useActions, useValues } from 'kea'
import { RefObject, useEffect, useRef } from 'react'

import { LemonButton, LemonCollapse, LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'

interface EditWithAgentPromptProps extends MessageTemplateLogicProps {
    containerRef: RefObject<HTMLDivElement>
}

export function EditWithAgentPrompt({ containerRef, ...props }: EditWithAgentPromptProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { changeSentence, agentPrompt, copyAgentPromptDisabledReason } = useValues(logic)
    const { setChangeSentence, copyAgentPrompt } = useActions(logic)
    const sentenceRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        const sentence = sentenceRef.current
        if (sentence) {
            sentence.focus()
            sentence.setSelectionRange(sentence.value.length, sentence.value.length)
        }
    }, [])

    return (
        <div
            ref={containerRef}
            role="dialog"
            aria-label="Edit with your agent"
            className="flex flex-col gap-2 p-1 w-96 max-w-full"
        >
            <LemonLabel htmlFor="message-template-change-sentence">Describe the change</LemonLabel>
            <LemonTextArea
                id="message-template-change-sentence"
                ref={sentenceRef}
                value={changeSentence}
                onChange={setChangeSentence}
                onPressCmdEnter={copyAgentPrompt}
                minRows={3}
                data-attr="message-template-change-sentence"
            />
            <div className="flex justify-end">
                <LemonButton
                    data-attr="message-template-copy-agent-prompt"
                    type="primary"
                    size="small"
                    onClick={copyAgentPrompt}
                    disabledReason={copyAgentPromptDisabledReason}
                >
                    Copy prompt
                </LemonButton>
            </div>
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'prompt',
                        header: 'Show full prompt',
                        content: (
                            <div
                                className="whitespace-pre-wrap break-words font-mono text-xs"
                                data-attr="message-template-agent-prompt"
                            >
                                {agentPrompt}
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
