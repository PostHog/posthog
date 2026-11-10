import { useActions, useValues } from 'kea'
import { ReactNode, useMemo } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import {
    SandboxSenderChoice,
    SandboxSenderChoiceContext,
} from 'scenes/hog-functions/email-templater/SandboxSenderChoiceContext'

import { workflowLogic } from '../../../workflowLogic'
import { emailSenderControlLogic } from './emailSenderControlLogic'
import { OwnOnlySetting } from './emailStepVariants'

const DROPPED_SETTING_LABELS: Record<OwnOnlySetting, string> = {
    sender_override: 'The custom From name and address',
    several_senders: 'Sending from several senders',
    reply_to: 'The Reply-To address',
    cc_bcc: 'CC and BCC recipients',
    tracking_off: 'Open and click tracking turned off',
    utm_tags: 'UTM tags on links',
}

export function SandboxSenderChoiceProvider({
    actionId,
    children,
}: {
    actionId: string
    children: ReactNode
}): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    const logic = emailSenderControlLogic({ workflowLogicProps: logicProps, actionId })
    const { action, showSandboxOption, sandboxStatus, pendingSwitch } = useValues(logic)
    const { chooseSender, confirmSwitch, cancelSwitch } = useActions(logic)

    const selected = action?.type === 'email_sandbox'
    const fromLine = sandboxStatus?.from_address
        ? `${sandboxStatus.display_name} <${sandboxStatus.from_address}>`
        : null
    const choice = useMemo<SandboxSenderChoice | null>(
        () => (showSandboxOption ? { selected, fromLine, onSelect: () => chooseSender('sandbox') } : null),
        [showSandboxOption, selected, fromLine, chooseSender]
    )

    return (
        <SandboxSenderChoiceContext.Provider value={choice}>
            {children}
            <LemonModal
                isOpen={!!pendingSwitch}
                onClose={cancelSwitch}
                title="Switch to the sandbox sender?"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={cancelSwitch}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={confirmSwitch}
                            data-attr="workflow-email-sender-switch-confirm"
                        >
                            Switch sender
                        </LemonButton>
                    </>
                }
            >
                <p>The sandbox sender doesn't support these settings, so this step loses them:</p>
                <ul className="list-disc pl-6">
                    {pendingSwitch?.droppedSettings.map((setting) => (
                        <li key={setting}>{DROPPED_SETTING_LABELS[setting]}</li>
                    ))}
                </ul>
            </LemonModal>
        </SandboxSenderChoiceContext.Provider>
    )
}
