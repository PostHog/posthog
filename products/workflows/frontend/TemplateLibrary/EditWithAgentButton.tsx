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
    const promptRef = useRef<HTMLDivElement>(null)
    const triggerRef = useFocusBackOnClose(agentPromptOpen, promptRef)

    return (
        <Popover
            visible={agentPromptOpen}
            // Popover reports a press on its own trigger as outside, so the trigger's click alone toggles it.
            onClickOutside={(event) => {
                if (!triggerRef.current?.contains(event.target as Node)) {
                    setAgentPromptOpen(false)
                }
            }}
            placement="bottom-end"
            fallbackPlacements={['bottom-start', 'top-end']}
            overlay={<AgentPrompt {...props} containerRef={promptRef} />}
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

/**
 * The popover unmounts its content shortly after it closes, which drops keyboard focus to the page's start. Focus that
 * is still inside the prompt goes back to the trigger; focus the person moved elsewhere stays where it is.
 */
function useFocusBackOnClose(open: boolean, promptRef: RefObject<HTMLElement>): RefObject<HTMLButtonElement> {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const wasOpen = useRef(open)
    useEffect(() => {
        const focused = document.activeElement
        if (wasOpen.current && !open && (focused === document.body || promptRef.current?.contains(focused))) {
            triggerRef.current?.focus()
        }
        wasOpen.current = open
    }, [open, promptRef])
    return triggerRef
}

interface AgentPromptProps extends MessageTemplateLogicProps {
    containerRef: RefObject<HTMLDivElement>
}

function AgentPrompt({ containerRef, ...props }: AgentPromptProps): JSX.Element {
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
                            // Not a <pre>: global styles make every <pre> a scroll container, and a scroll container
                            // in this collapse inside the popover stays unpainted in Chromium until it scrolls.
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
