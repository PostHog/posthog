import { useMountedLogic, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSwitch, Link } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { urls } from 'scenes/urls'

import type {
    SignalScoutOutputDestinationsApi,
    SignalScoutSlackDestinationApi,
} from 'products/signals/frontend/generated/api.schemas'

interface ScoutSlackDestinationProps {
    destination?: SignalScoutSlackDestinationApi | null
    disabledReason?: string
    onChange: (outputDestinations: SignalScoutOutputDestinationsApi) => void
}

export function ScoutSlackDestination({
    destination,
    disabledReason,
    onChange,
}: ScoutSlackDestinationProps): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const integrations = slackIntegrations ?? []
    const configuredIntegration = destination
        ? integrations.find((integration) => integration.id === destination.integration_id)
        : undefined
    const selectedIntegration = configuredIntegration ?? (integrations.length === 1 ? integrations[0] : null)

    const selectWorkspace = (integrationId: number): void => {
        onChange({ slack: { integration_id: integrationId, channel: null } })
    }

    const selectChannel = (channel: string | null): void => {
        if (!channel || !selectedIntegration) {
            onChange({})
            return
        }
        onChange({
            slack: {
                integration_id: selectedIntegration.id,
                channel,
                thread_reports: destination?.thread_reports ?? false,
            },
        })
    }

    const setThreadReports = (threadReports: boolean): void => {
        // Toggle threading only against the stored destination's own workspace. Writing a fallback
        // integration id next to the stored channel would pair the channel with a different
        // workspace and break delivery, so require the configured integration to resolve here.
        if (!configuredIntegration || !destination?.channel) {
            return
        }
        onChange({
            slack: {
                integration_id: configuredIntegration.id,
                channel: destination.channel,
                thread_reports: threadReports,
            },
        })
    }

    const disableSlack = (): void => {
        onChange({})
    }

    const hasChannel = Boolean(destination?.channel)

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-2">
            <div className="flex flex-col min-w-0">
                <span className="text-xs text-default">Slack destination</span>
                <span className="text-[11.5px] text-muted">Post each scout run's output to a channel</span>
            </div>
            {integrationsLoading && slackIntegrations === undefined ? (
                <span className="text-xs text-muted">Loading Slack workspaces…</span>
            ) : integrations.length === 0 ? (
                <Link to={urls.settings('environment-integrations', 'integration-slack')}>
                    Connect a Slack workspace
                </Link>
            ) : (
                <div className="flex flex-col gap-2 max-w-md">
                    {integrations.length > 1 ? (
                        <LemonSelect
                            size="small"
                            value={selectedIntegration?.id ?? null}
                            options={integrations.map((integration) => ({
                                value: integration.id,
                                label: integration.display_name || `Slack workspace ${integration.id}`,
                            }))}
                            onChange={(integrationId) => integrationId != null && selectWorkspace(integrationId)}
                            placeholder="Select workspace"
                            disabledReason={disabledReason}
                        />
                    ) : null}
                    {selectedIntegration ? (
                        <div className="flex items-center gap-2">
                            <div className="flex-1 min-w-0">
                                <SlackChannelPicker
                                    integration={selectedIntegration}
                                    value={configuredIntegration ? (destination?.channel ?? undefined) : undefined}
                                    onChange={selectChannel}
                                    disabled={disabledReason !== undefined}
                                />
                            </div>
                            {hasChannel ? (
                                <LemonButton
                                    size="small"
                                    icon={<IconTrash />}
                                    onClick={disableSlack}
                                    tooltip="Turn off Slack notifications for this scout"
                                    disabledReason={disabledReason}
                                    aria-label="Turn off Slack notifications"
                                />
                            ) : null}
                        </div>
                    ) : null}
                    <span className="text-[11.5px] text-muted">
                        {hasChannel
                            ? 'PostHog must be in the channel. Invite it with '
                            : 'Pick a channel to turn notifications on. PostHog must be in the channel. Invite it with '}
                        <code>/invite @PostHog</code>.
                    </span>
                    {configuredIntegration && hasChannel ? (
                        <LemonSwitch
                            size="small"
                            checked={destination?.thread_reports ?? false}
                            onChange={setThreadReports}
                            disabledReason={disabledReason}
                            label="Post long reports as a thread"
                            tooltip="Post a short lead in the channel and split the rest by the report's headings into replies, so a long summary is not cut off."
                            bordered
                        />
                    ) : null}
                </div>
            )}
        </div>
    )
}
