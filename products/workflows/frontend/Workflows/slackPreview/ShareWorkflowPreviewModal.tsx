import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonInput, LemonLabel, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { SlackDestinationPicker } from 'lib/components/Comments/SlackDestinationPicker'

import { ShareWorkflowPreviewLogicProps, shareWorkflowPreviewLogic } from './shareWorkflowPreviewLogic'

export function ShareWorkflowPreviewModal(props: ShareWorkflowPreviewLogicProps): JSX.Element {
    const logic = shareWorkflowPreviewLogic(props)
    const {
        isOpen,
        integrationId,
        channel,
        threadLink,
        note,
        emailSteps,
        excludedEmailIds,
        isSubmitting,
        submitDisabledReason,
    } = useValues(logic)
    const { closeModal, setIntegrationId, setChannel, setThreadLink, setNote, toggleEmail, submit } = useActions(logic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            width={560}
            title="Share preview to Slack"
            description="Post this workflow's steps and an image of each email to Slack, so your team can review them before anything is sent."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={isSubmitting ? 'Sharing…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submit}
                        loading={isSubmitting}
                        disabledReason={submitDisabledReason}
                        data-attr="workflow-share-preview-submit"
                    >
                        Share to Slack
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <SlackDestinationPicker
                    integrationId={integrationId}
                    channel={channel}
                    onIntegrationChange={setIntegrationId}
                    onChannelChange={setChannel}
                />
                <div className="flex flex-col gap-1">
                    <LemonLabel info="Posts in that message's thread instead of the channel above.">
                        Reply in a thread (optional)
                    </LemonLabel>
                    <LemonInput
                        value={threadLink}
                        onChange={setThreadLink}
                        placeholder="Paste a link to a Slack message"
                        data-attr="workflow-share-preview-thread-link"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Note (optional)</LemonLabel>
                    <LemonTextArea value={note} onChange={setNote} placeholder="What should your team look at?" />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Emails</LemonLabel>
                    {emailSteps.length === 0 ? (
                        <p className="text-secondary m-0">
                            This workflow has no email steps. The preview shares its steps only.
                        </p>
                    ) : (
                        emailSteps.map((step) => (
                            <LemonCheckbox
                                key={step.actionId}
                                checked={!excludedEmailIds.includes(step.actionId)}
                                onChange={() => toggleEmail(step.actionId)}
                                label={step.subject || step.stepName}
                            />
                        ))
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
