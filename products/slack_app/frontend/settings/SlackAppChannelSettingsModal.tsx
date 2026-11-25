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
            onClose={closeChannelModal}
            width={520}
            title={title}
            description="A channel setting wins over each person's own setting. Anyone in the project can change it."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeChannelModal}>
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
