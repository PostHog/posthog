import { useActions, useValues } from 'kea'
import { RefObject, useEffect, useRef } from 'react'

import { LemonButton, Popover } from '@posthog/lemon-ui'

import { EditWithAgentPrompt } from './EditWithAgentPrompt'
import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'

export function EditWithAgentButton(props: MessageTemplateLogicProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { agentPromptOpen, templateLoading } = useValues(logic)
    const { setAgentPromptOpen } = useActions(logic)
    const loadingReason = templateLoading ? 'Wait for the template to load' : undefined
    const promptRef = useRef<HTMLDivElement>(null)
    const triggerRef = useFocusBackOnClose(agentPromptOpen, promptRef)

    return (
        <Popover
            visible={agentPromptOpen}
            onClickOutside={(event) => {
                if (!isPressOnTrigger(event, triggerRef)) {
                    setAgentPromptOpen(false)
                }
            }}
            placement="bottom-end"
            fallbackPlacements={['bottom-start', 'top-end']}
            overlay={<EditWithAgentPrompt {...props} containerRef={promptRef} />}
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
            >
                Edit with your agent
            </LemonButton>
        </Popover>
    )
}

function isPressOnTrigger(event: Event, triggerRef: RefObject<HTMLButtonElement>): boolean {
    return !(event instanceof KeyboardEvent) && !!triggerRef.current?.contains(event.target as Node)
}

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
