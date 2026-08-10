import { useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackUserPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { urls } from 'scenes/urls'

import type {
    SignalScoutOutputDestinationsApi,
    SignalScoutSlackDestinationApi,
} from 'products/signals/frontend/generated/api.schemas'

// Mirrors MAX_SCOUT_SLACK_DM_TARGETS on the backend serializer.
const MAX_DM_RECIPIENTS = 5

type SlackTargetMode = 'channel' | 'dm'

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

    const hasChannel = Boolean(destination?.channel)
    const hasUsers = Boolean(destination?.users?.length)
    const hasTarget = hasChannel || hasUsers

    // The saved destination decides the mode; local state only carries the toggle while nothing is saved yet.
    const [pendingMode, setPendingMode] = useState<SlackTargetMode>('channel')
    const mode: SlackTargetMode = hasUsers ? 'dm' : hasChannel ? 'channel' : pendingMode

    const selectWorkspace = (integrationId: number): void => {
        onChange({ slack: { integration_id: integrationId, channel: null } })
    }

    const selectMode = (nextMode: SlackTargetMode): void => {
        setPendingMode(nextMode)
        if (hasTarget && selectedIntegration) {
            // Switching mode drops the other mode's target so exactly one is ever active.
            onChange({ slack: { integration_id: selectedIntegration.id, channel: null } })
        }
    }

    const selectChannel = (channel: string | null): void => {
        if (!channel || !selectedIntegration) {
            onChange({})
            return
        }
        onChange({
            slack: { integration_id: selectedIntegration.id, channel },
        })
    }

    const selectUsers = (users: string[]): void => {
        if (!selectedIntegration) {
            onChange({})
            return
        }
        if (!users.length) {
            onChange({ slack: { integration_id: selectedIntegration.id, channel: null } })
            return
        }
        onChange({
            slack: { integration_id: selectedIntegration.id, users: users.slice(0, MAX_DM_RECIPIENTS) },
        })
    }

    const disableSlack = (): void => {
        onChange({})
    }

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-2">
            <div className="flex flex-col min-w-0">
                <span className="text-xs text-default">Slack destination</span>
                <span className="text-[11.5px] text-muted">
                    Post each scout run's output to a channel, or send it as a direct message
                </span>
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
                        <>
                            <LemonSegmentedButton
                                size="small"
                                value={mode}
                                onChange={(nextMode) => selectMode(nextMode as SlackTargetMode)}
                                options={[
                                    { value: 'channel', label: 'Channel', disabledReason },
                                    { value: 'dm', label: 'Direct message', disabledReason },
                                ]}
                            />
                            <div className="flex items-center gap-2">
                                <div className="flex-1 min-w-0">
                                    {mode === 'channel' ? (
                                        <SlackChannelPicker
                                            integration={selectedIntegration}
                                            value={
                                                configuredIntegration ? (destination?.channel ?? undefined) : undefined
                                            }
                                            onChange={selectChannel}
                                            disabled={disabledReason !== undefined}
                                        />
                                    ) : (
                                        <SlackUserPicker
                                            integration={selectedIntegration}
                                            values={configuredIntegration ? (destination?.users ?? []) : []}
                                            onChange={selectUsers}
                                            disabled={disabledReason !== undefined}
                                            maxUsers={MAX_DM_RECIPIENTS}
                                        />
                                    )}
                                </div>
                                {hasTarget ? (
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
                        </>
                    ) : null}
                    {mode === 'channel' ? (
                        <span className="text-[11.5px] text-muted">
                            {hasChannel
                                ? 'PostHog must be in the channel. Invite it with '
                                : 'Pick a channel to turn notifications on. PostHog must be in the channel. Invite it with '}
                            <code>/invite @PostHog</code>.
                        </span>
                    ) : (
                        <span className="text-[11.5px] text-muted">
                            {hasUsers
                                ? `Each person gets their own direct message from the PostHog app (up to ${MAX_DM_RECIPIENTS} people).`
                                : `Pick up to ${MAX_DM_RECIPIENTS} people to turn notifications on. Each person gets their own direct message from the PostHog app.`}
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}
