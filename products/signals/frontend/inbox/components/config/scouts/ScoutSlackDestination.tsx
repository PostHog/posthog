import { useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect, LemonSwitch, Link } from '@posthog/lemon-ui'

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

    // The toggle is view state only: switching it must never write, or an exploratory click would
    // wipe a live destination. The saved target is replaced only when a new target is picked.
    const [pendingMode, setPendingMode] = useState<SlackTargetMode | null>(null)
    const mode: SlackTargetMode = pendingMode ?? (hasUsers ? 'dm' : 'channel')

    const selectWorkspace = (integrationId: number): void => {
        // Switching workspace clears the target, so pin the toggle to the mode the user was in.
        setPendingMode(mode)
        onChange({ slack: { integration_id: integrationId, channel: null } })
    }

    const selectMode = (nextMode: SlackTargetMode): void => {
        setPendingMode(nextMode)
    }

    const selectChannel = (channel: string | null): void => {
        if (!channel || !selectedIntegration) {
            // An empty picker still emits clears (e.g. Backspace in its input), so only a picker
            // whose own target is saved may clear — otherwise viewing the alternate mode while the
            // other target is live would wipe that target.
            if (hasChannel) {
                onChange({})
            }
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

    const selectUsers = (users: string[]): void => {
        if (!selectedIntegration) {
            return
        }
        if (!users.length) {
            if (!hasUsers) {
                // Same guard as selectChannel: an empty DM picker's clear must not wipe a saved channel.
                return
            }
            // Removing the last recipient empties the saved destination; without pinning the mode
            // the toggle would fall back to its channel default and swap the picker mid-edit.
            setPendingMode('dm')
            onChange({ slack: { integration_id: selectedIntegration.id, channel: null } })
            return
        }
        onChange({
            slack: { integration_id: selectedIntegration.id, users: users.slice(0, MAX_DM_RECIPIENTS) },
        })
    }

    const disableSlack = (): void => {
        setPendingMode(mode)
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
                        <>
                            <span className="text-[11.5px] text-muted">
                                {hasChannel
                                    ? 'PostHog must be in the channel. Invite it with '
                                    : hasUsers
                                      ? 'Direct messages stay on until you pick a channel to replace them. PostHog must be in the channel. Invite it with '
                                      : 'Pick a channel to turn notifications on. PostHog must be in the channel. Invite it with '}
                                <code>/invite @PostHog</code>.
                            </span>
                            {configuredIntegration && hasChannel ? (
                                <LemonSwitch
                                    size="small"
                                    checked={destination?.thread_reports ?? false}
                                    onChange={setThreadReports}
                                    disabledReason={disabledReason}
                                    label="Post reports as a thread"
                                    tooltip="Post a short lead in the channel and split the rest by the report's headings into replies, so the channel stays readable and a long summary is not cut off."
                                    bordered
                                />
                            ) : null}
                        </>
                    ) : (
                        <span className="text-[11.5px] text-muted">
                            {hasUsers
                                ? `Each person gets their own direct message from the PostHog app (up to ${MAX_DM_RECIPIENTS} people).`
                                : hasChannel
                                  ? `The channel stays on until you pick up to ${MAX_DM_RECIPIENTS} people to replace it. Each person gets their own direct message from the PostHog app.`
                                  : `Pick up to ${MAX_DM_RECIPIENTS} people to turn notifications on. Each person gets their own direct message from the PostHog app.`}
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}
