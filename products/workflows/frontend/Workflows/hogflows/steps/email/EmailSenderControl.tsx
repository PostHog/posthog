import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { workflowLogic } from '../../../workflowLogic'
import { SenderChoice, emailSenderControlLogic } from './emailSenderControlLogic'
import { OwnOnlySetting } from './emailStepVariants'

const DROPPED_SETTING_LABELS: Record<OwnOnlySetting, string> = {
    sender_override: 'The custom From name and address',
    several_senders: 'Sending from several senders',
    reply_to: 'The Reply-To address',
    cc_bcc: 'CC and BCC recipients',
    tracking_off: 'Open and click tracking turned off',
    utm_tags: 'UTM tags on links',
}

/** Chooses between the project's verified senders and the sandbox sender. Hidden unless the sandbox sender is on offer. */
export function EmailSenderControl({ actionId }: { actionId: string }): JSX.Element | null {
    const { logicProps } = useValues(workflowLogic)
    const logic = emailSenderControlLogic({ workflowLogicProps: logicProps, actionId })
    const { ownSenders, selectedSender, showSandboxOption, pendingSwitch } = useValues(logic)
    const { chooseSender, confirmSwitch, cancelSwitch } = useActions(logic)

    if (!showSandboxOption) {
        return null
    }

    return (
        <>
            <LemonField.Pure
                label="Sender"
                help="The sandbox sender works before you verify a domain. It only delivers to verified members of your organization."
            >
                <LemonSelect<SenderChoice>
                    fullWidth
                    value={selectedSender ?? undefined}
                    onChange={chooseSender}
                    placeholder="Choose a sender"
                    options={[
                        ...ownSenders.map((sender) => ({ value: sender.id, label: sender.display_name })),
                        { value: 'sandbox' as const, label: 'Sandbox sender' },
                    ]}
                    data-attr="workflow-email-sender-control"
                />
            </LemonField.Pure>
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
        </>
    )
}
