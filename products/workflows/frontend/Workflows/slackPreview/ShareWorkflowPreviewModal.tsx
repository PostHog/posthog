import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonTextArea,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { SlackDestinationPicker } from 'lib/components/Comments/SlackDestinationPicker'
import { useIntegrationManagementRestriction } from 'lib/integrations/integrationPermissions'

import { isSlackMessageLink } from './shareDisabledReason'
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
        canUploadImages,
    } = useValues(logic)
    const reconnectRestriction = useIntegrationManagementRestriction()
    const { closeModal, setIntegrationId, setChannel, setThreadLink, setNote, toggleEmail, submit } = useActions(logic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            closable={!isSubmitting}
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
                    <LemonLabel htmlFor="workflow-share-preview-thread-link" showOptional>
                        Reply in a thread
                    </LemonLabel>
                    <LemonInput
                        id="workflow-share-preview-thread-link"
                        value={threadLink}
                        onChange={setThreadLink}
                        placeholder="Paste a link to a Slack message"
                        data-attr="workflow-share-preview-thread-link"
                    />
                    <ThreadLinkHint threadLink={threadLink} hasChannel={!!channel} />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="workflow-share-preview-note" showOptional>
                        Note
                    </LemonLabel>
                    <LemonTextArea
                        id="workflow-share-preview-note"
                        value={note}
                        onChange={setNote}
                        placeholder="What should your team look at?"
                    />
                </div>
                {!canUploadImages && emailSteps.length > 0 ? (
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Reconnect Slack',
                            to: api.integrations.authorizeUrl({ kind: 'slack', next: window.location.pathname }),
                            disableClientSideRouting: true,
                            disabledReason: reconnectRestriction ?? undefined,
                            'data-attr': 'workflow-share-preview-slack-reconnect',
                        }}
                    >
                        This Slack connection cannot upload images.{' '}
                        {reconnectRestriction
                            ? 'Ask a project admin to reconnect Slack to share the emails.'
                            : 'Reconnect Slack to share the emails.'}
                    </LemonBanner>
                ) : null}
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

function ThreadLinkHint({ threadLink, hasChannel }: { threadLink: string; hasChannel: boolean }): JSX.Element | null {
    if (!threadLink.trim()) {
        return null
    }
    if (!isSlackMessageLink(threadLink)) {
        return (
            <p className="text-danger text-xs m-0">
                This is not a link to a Slack message. In Slack, open the message menu and choose Copy link.
            </p>
        )
    }
    return (
        <p className="text-secondary text-xs m-0">
            {hasChannel
                ? "The preview goes into this message's thread, not the channel above."
                : "The preview goes into this message's thread."}
        </p>
    )
}
