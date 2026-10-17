import { useActions, useValues } from 'kea'
import { RefObject, useEffect, useRef } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonLabel, LemonTextArea, Popover } from '@posthog/lemon-ui'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'

export function EditWithAgentButton(props: MessageTemplateLogicProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { agentPromptOpen, templateLoading } = useValues(logic)
    const { setAgentPromptOpen, copyHtmlFile } = useActions(logic)
    const loadingReason = templateLoading ? 'Wait for the template to load' : undefined
    const triggerRef = useFocusBackOnClose(agentPromptOpen)

    return (
        <Popover
            visible={agentPromptOpen}
            onClickOutside={() => setAgentPromptOpen(false)}
            placement="bottom-end"
            fallbackPlacements={['bottom-start', 'top-end']}
            overlay={<AgentPrompt {...props} />}
        >
            <LemonButton
                ref={triggerRef}
                aria-haspopup="dialog"
                aria-expanded={agentPromptOpen}
                data-attr="message-template-edit-with-agent"
                type="primary"
                size="small"
                onClick={() => setAgentPromptOpen(!agentPromptOpen)}
                disabledReason={loadingReason}
                sideAction={{
                    'data-attr': 'message-template-copy-options',
                    'aria-label': 'More ways to copy this template',
                    disabledReason: loadingReason,
                    dropdown: {
                        placement: 'bottom-end',
                        overlay: (
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: 'Copy HTML file',
                                        icon: <IconCopy />,
                                        onClick: copyHtmlFile,
                                        'data-attr': 'message-template-copy-html-file',
                                    },
                                ]}
                            />
                        ),
                    },
                }}
            >
                Edit with your agent
            </LemonButton>
        </Popover>
    )
}

/** Closing the popover unmounts the focused text area, so keyboard focus would fall back to the page's start. */
function useFocusBackOnClose(open: boolean): RefObject<HTMLButtonElement> {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const wasOpen = useRef(open)
    useEffect(() => {
        if (wasOpen.current && !open && document.activeElement === document.body) {
            triggerRef.current?.focus()
        }
        wasOpen.current = open
    }, [open])
    return triggerRef
}

function AgentPrompt(props: MessageTemplateLogicProps): JSX.Element {
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
        <div className="flex flex-col gap-2 p-1 w-96 max-w-full">
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
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'prompt',
                        header: 'Show full prompt',
                        content: (
                            <pre
                                className="m-0 whitespace-pre-wrap break-words text-xs"
                                data-attr="message-template-agent-prompt"
                            >
                                {agentPrompt}
                            </pre>
                        ),
                    },
                ]}
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
        </div>
    )
}
