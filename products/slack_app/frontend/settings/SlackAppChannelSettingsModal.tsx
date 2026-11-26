import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'

import type { IntegrationType } from '~/types'

import { SlackAppChannelSettingsForm } from './SlackAppChannelSettingsForm'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'
import { slackChannelLabel } from './slackChannelLabel'

export function SlackAppChannelSettingsModal({ integration }: { integration: IntegrationType }): JSX.Element {
    const { channelDraft, isEditingChannel, channelSaving, channelSaveDisabledReason } =
        useValues(slackAppSettingsLogic)
    const { closeChannelModal, saveChannelDraft } = useActions(slackAppSettingsLogic)
    const { slackChannels } = useValues(slackIntegrationLogic({ id: integration.id }))

    const editedChannelId = isEditingChannel ? channelDraft?.slack_channel_id : null
    const title = editedChannelId
        ? `Settings for ${slackChannelLabel(
              slackChannels.find((channel) => channel.id === editedChannelId),
              editedChannelId
          )}`
        : 'Add channel settings'

    return (
        <LemonModal
            isOpen={channelDraft !== null}
            // A save in flight closes the modal when it finishes, so the modal stays open until then.
            onClose={channelSaving ? undefined : closeChannelModal}
            width={520}
            title={title}
            description="A channel's project and repository win over each person's own. Anyone in your organization can change them."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeChannelModal}
                        disabledReason={channelSaving ? 'Saving' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveChannelDraft}
                        loading={channelSaving}
                        disabledReason={channelSaveDisabledReason}
                        data-attr="slack-app-channel-settings-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            {channelDraft ? <SlackAppChannelSettingsForm integration={integration} draft={channelDraft} /> : null}
        </LemonModal>
    )
}
