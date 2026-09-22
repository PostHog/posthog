import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { isSlackMemberTarget, slackChannelDisplayName } from 'lib/integrations/slackChannel'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { IconSlack } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { userAutonomyLogic } from '../../logics/userAutonomyLogic'
import { PRIORITY_THRESHOLD_OPTIONS, SignalReportPriority, SignalUserAutonomyConfig } from '../../types'
import { ConfigCardHeader } from './ConfigCardHeader'

const NOTIFY_ALL_VALUE = '__all__'

type SlackTargetMode = 'dm' | 'channel'

/** Minimum report priority that triggers a Slack ping. "All priorities" maps to a null min-priority. */
const MIN_PRIORITY_OPTIONS: { value: SignalReportPriority | typeof NOTIFY_ALL_VALUE; label: string }[] = [
    { value: NOTIFY_ALL_VALUE, label: 'All priorities' },
    ...PRIORITY_THRESHOLD_OPTIONS,
]

/** Icon + title + description header shared by all the Slack cards in this section. */
function SlackCardHeader({ title, description }: { title: string; description: ReactNode }): JSX.Element {
    return (
        <ConfigCardHeader
            icon={<IconSlack className="size-5 shrink-0 mt-0.5 grayscale" />}
            title={title}
            description={description}
        />
    )
}

/** Shown when there's no Slack workspace connected – links out to integration settings. */
/** The Settings tab separates these cards with rules inside its own card; the legacy rail frames each one. */
function slackCardClassName(redesign: boolean): string {
    return redesign
        ? 'flex flex-col gap-3 border-b border-primary py-2.5 first:pt-0 last:border-b-0 last:pb-0'
        : 'flex flex-col gap-3 rounded border bg-bg-light px-3 py-2.5'
}

function ConnectSlackPrompt(): JSX.Element {
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    return (
        <Link
            to={urls.settings('environment-integrations', 'integration-slack')}
            className={
                redesign
                    ? 'group -mx-2 flex items-center justify-between gap-3 rounded px-2 py-2.5 no-underline transition-colors hover:bg-surface-secondary'
                    : 'group flex items-center justify-between gap-3 rounded border bg-bg-light px-3 py-2.5 no-underline transition-colors hover:border-primary-3000 hover:bg-bg-3000'
            }
        >
            <SlackCardHeader
                title="Connect a Slack workspace"
                description="Connect Slack to post reports to a team channel and get pinged when you're a suggested reviewer."
            />
            <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
        </Link>
    )
}

/**
 * Team-wide channel where every actionable report is posted regardless of the suggested reviewer,
 * backed by `default_slack_notification_channel` on `signalTeamConfigLogic`. Toggling off (or
 * clearing the channel) disables the team default. The backend routes the team channel through the
 * team's first Slack integration (`_get_team_slack_integration`), so we target `integrations[0]`
 * here too.
 */
function TeamChannelCard({ integration }: { integration: IntegrationType }): JSX.Element {
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    const { teamConfig, teamConfigLoading } = useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)
    // Local view state: the toggle is on but no channel has been picked yet. A saved
    // channel implies enabled on its own, so this only bridges the picking moment.
    const [pickerExpanded, setPickerExpanded] = useState(false)

    const channel = teamConfig?.default_slack_notification_channel ?? null
    const showPicker = pickerExpanded || !!channel

    const onToggleEnabled = (enabled: boolean): void => {
        setPickerExpanded(enabled)
        if (!enabled && channel) {
            patchTeamConfig({ default_slack_notification_channel: null })
        }
    }

    return (
        <div className={slackCardClassName(redesign)}>
            <div className="flex items-start justify-between gap-4">
                <SlackCardHeader
                    title="Notify the whole team"
                    description={
                        <>
                            Post every report to one channel, whether or not a reviewer is suggested. PostHog must be in
                            the channel. Invite it with <code>/invite @PostHog</code>.
                        </>
                    }
                />
                <LemonSwitch
                    checked={showPicker}
                    onChange={onToggleEnabled}
                    disabled={teamConfigLoading && teamConfig === null}
                    aria-label="Enable team-wide Slack notifications"
                />
            </div>

            {showPicker && (
                <div className="flex flex-col gap-1 min-w-0 max-w-md border-t border-primary border-dashed pt-3">
                    <span className="text-xs text-secondary">Channel</span>
                    <SlackChannelPicker
                        integration={integration}
                        value={channel ?? undefined}
                        onChange={(next) => patchTeamConfig({ default_slack_notification_channel: next })}
                    />
                </div>
            )}
        </div>
    )
}

/** Where a saved config sends this user's reviewer pings, and whether that counts as enabled. */
function readSlackTarget(
    config: SignalUserAutonomyConfig | null,
    integrations: IntegrationType[]
): {
    selectedIntegrationId: number | null
    integration: IntegrationType | null
    channel: string | null
    savedMode: SlackTargetMode
    /** The Slack account a saved direct message goes to, e.g. `@sam`. */
    recipient: string | null
    enabled: boolean
} {
    const selectedIntegrationId = config?.slack_notification_integration_id ?? null
    // Workspace is shared with the team default. Default to the only workspace, or the user's saved pick.
    const integration =
        integrations.find((i) => i.id === selectedIntegrationId) ?? (integrations.length === 1 ? integrations[0] : null)
    const channel = config?.slack_notification_channel ?? null
    const savedMode: SlackTargetMode = channel && !isSlackMemberTarget(channel) ? 'channel' : 'dm'
    return {
        selectedIntegrationId,
        integration,
        channel,
        savedMode,
        recipient: savedMode === 'dm' && channel ? slackChannelDisplayName(channel) : null,
        enabled: !!integration && !!channel,
    }
}

function DirectMessageTarget({
    recipient,
    saving,
    onEnable,
}: {
    recipient: string | null
    saving: boolean
    onEnable: () => void
}): JSX.Element {
    if (recipient) {
        return <span className="text-xs text-secondary">PostHog sends these to {recipient} in Slack.</span>
    }
    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                onClick={onEnable}
                loading={saving}
                disabledReason={saving ? 'Setting this up…' : undefined}
            >
                Send me a direct message
            </LemonButton>
            <span className="text-xs text-secondary">
                PostHog finds you in the workspace and messages you there. There is no channel to create.
            </span>
        </>
    )
}

function ChannelTarget({
    integration,
    value,
    onChange,
}: {
    integration: IntegrationType
    value: string | undefined
    onChange: (next: string | null) => void
}): JSX.Element {
    return (
        <>
            <SlackChannelPicker integration={integration} value={value} onChange={onChange} />
            <span className="text-xs text-secondary">
                PostHog must be in the channel. Invite it with <code>/invite @PostHog</code>.
            </span>
        </>
    )
}

/**
 * Per-user Slack notification controls – a cloud port of desktop's
 * `SlackInboxNotificationsSettings` / `SignalSlackNotificationsSettings`.
 * Notifications are enabled when an integration + target are both set; the
 * enable toggle clears them to disable. Min-priority gates which reports ping.
 * Backed by the `slack_notification_*` fields on `userAutonomyLogic`.
 */
function PerUserNotificationCard({ integrations }: { integrations: IntegrationType[] }): JSX.Element {
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    const { autonomyConfig, autonomyConfigLoading, slackNotificationsSaving, slackPickersExpanded } =
        useValues(userAutonomyLogic)
    const { updateSlackNotifications, setSlackPickersExpanded } = useActions(userAutonomyLogic)

    const { selectedIntegrationId, integration, channel, savedMode, recipient, enabled } = readSlackTarget(
        autonomyConfig,
        integrations
    )
    const minPriority = autonomyConfig?.slack_notification_min_priority ?? null

    // The toggle is view state only: switching it must never write, or an exploratory click would
    // clear a saved target. A direct message is the default because it needs no channel set up.
    const [pendingMode, setPendingMode] = useState<SlackTargetMode | null>(null)
    const mode = pendingMode ?? savedMode

    const onToggleEnabled = (enabled: boolean): void => {
        if (enabled) {
            // With one workspace there is nothing to pick, so this also sets the direct message up.
            setSlackPickersExpanded(true)
            if (integration && selectedIntegrationId === null) {
                setPendingMode('dm')
                updateSlackNotifications({ integrationId: integration.id, directMessage: true })
            }
        } else {
            setPendingMode(null)
            setSlackPickersExpanded(false)
            updateSlackNotifications({ integrationId: null, channel: null })
        }
    }

    const onWorkspaceChange = (integrationId: number): void => {
        // The target won't exist in the new workspace. Pin the toggle to the mode the user was in.
        setPendingMode(mode)
        updateSlackNotifications({ integrationId, channel: null })
    }

    const onSendDirectMessages = (): void => {
        if (!integration) {
            return
        }
        setPendingMode('dm')
        updateSlackNotifications({ integrationId: integration.id, directMessage: true })
    }

    const onChannelChange = (next: string | null): void => {
        if (next === null) {
            // An empty picker still emits clears (e.g. Backspace in its input), so only a picker
            // whose own target is saved may clear – otherwise viewing it would wipe a saved DM.
            if (savedMode === 'channel' && channel) {
                setPendingMode('channel')
                updateSlackNotifications({ channel: null })
            }
            return
        }
        if (!integration) {
            return
        }
        updateSlackNotifications({ integrationId: integration.id, channel: next })
    }

    const onMinPriorityChange = (value: string): void => {
        updateSlackNotifications({
            minPriority: value === NOTIFY_ALL_VALUE ? null : (value as SignalReportPriority),
        })
    }

    // "On" means the controls are visible, which a saved integration or target implies on its own.
    const showPickers = slackPickersExpanded || selectedIntegrationId !== null || !!channel

    return (
        <div className={slackCardClassName(redesign)}>
            <div className="flex items-start justify-between gap-4">
                <SlackCardHeader
                    title="Notify me directly"
                    description="Get pinged when you're a suggested reviewer. PostHog can send you a direct message, or post in a channel you pick."
                />
                <LemonSwitch
                    checked={showPickers}
                    onChange={onToggleEnabled}
                    disabled={slackNotificationsSaving || (autonomyConfigLoading && autonomyConfig === null)}
                    aria-label="Enable Slack notifications"
                />
            </div>

            {showPickers && (
                <div className="flex flex-col gap-3 border-t border-primary border-dashed pt-3">
                    {integrations.length > 1 && (
                        <div className="flex flex-col gap-1 min-w-0">
                            <span className="text-xs text-secondary">Workspace</span>
                            <LemonSelect
                                className="max-w-[260px]"
                                value={integration?.id ?? null}
                                options={integrations.map((i) => ({
                                    value: i.id,
                                    label: i.display_name || `Slack workspace ${i.id}`,
                                }))}
                                onChange={(next) => next != null && onWorkspaceChange(next)}
                                placeholder="Select workspace"
                            />
                        </div>
                    )}

                    {integration && (
                        <div className="flex flex-col gap-2 min-w-0 max-w-md">
                            <LemonSegmentedButton
                                size="small"
                                value={mode}
                                onChange={(next) => setPendingMode(next as SlackTargetMode)}
                                options={[
                                    { value: 'dm', label: 'Direct message' },
                                    { value: 'channel', label: 'Channel' },
                                ]}
                            />
                            {mode === 'dm' ? (
                                <DirectMessageTarget
                                    recipient={recipient}
                                    saving={slackNotificationsSaving}
                                    onEnable={onSendDirectMessages}
                                />
                            ) : (
                                <ChannelTarget
                                    integration={integration}
                                    value={savedMode === 'channel' && channel ? channel : undefined}
                                    onChange={onChannelChange}
                                />
                            )}
                        </div>
                    )}

                    <div className="flex flex-col gap-1 min-w-0">
                        <span className="text-xs text-secondary">Min. priority</span>
                        <LemonSelect
                            className="max-w-[240px]"
                            value={minPriority ?? NOTIFY_ALL_VALUE}
                            options={MIN_PRIORITY_OPTIONS}
                            disabledReason={!enabled ? 'Choose where to send these first' : undefined}
                            onChange={onMinPriorityChange}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}

/** Slack inbox notification settings: a team-wide channel plus per-user reviewer pings. */
export function SlackNotificationsSection(): JSX.Element {
    useMountedLogic(integrationsLogic)
    useMountedLogic(userAutonomyLogic)
    // Mounted here (not just in TeamChannelCard) so the team config fetch runs in
    // parallel with the integrations load instead of waiting out the skeleton.
    useMountedLogic(signalTeamConfigLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)

    if (integrationsLoading && slackIntegrations === undefined) {
        return <LemonSkeleton className="h-20 w-full" />
    }

    const integrations = slackIntegrations ?? []
    if (integrations.length === 0) {
        return <ConnectSlackPrompt />
    }

    return (
        <div className="flex flex-col gap-3">
            <TeamChannelCard integration={integrations[0]} />
            <PerUserNotificationCard integrations={integrations} />
        </div>
    )
}
