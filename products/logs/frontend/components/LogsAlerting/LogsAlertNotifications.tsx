import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { urls } from 'scenes/urls'

import { LOGS_ALERT_NOTIFICATION_TYPE_OPTIONS, logsAlertNotificationLogic } from './logsAlertNotificationLogic'
import {
    getHogFunctionEventKind,
    LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
    LOGS_ALERT_NOTIFICATION_TYPE_TEAMS,
    LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK,
    PendingLogsAlertNotification,
    resolveGroupLabel,
} from './logsAlertUtils'

export function LogsAlertNotifications({ alertId }: { alertId?: string }): JSX.Element {
    const {
        existingHogFunctionsLoading,
        destinationGroups,
        pendingNotifications,
        firstSlackIntegration,
        selectedType,
        slackChannelValue,
        webhookUrl,
    } = useValues(logsAlertNotificationLogic)
    const {
        addPendingNotification,
        removePendingNotification,
        deleteExistingDestination,
        setSelectedType,
        setSlackChannelValue,
        setWebhookUrl,
    } = useActions(logsAlertNotificationLogic)

    const slackLogic = slackIntegrationLogic({ id: firstSlackIntegration?.id ?? 0 })
    const { slackChannels } = useValues(slackLogic)
    const { loadAllSlackChannels } = useActions(slackLogic)

    useEffect(() => {
        if (firstSlackIntegration) {
            loadAllSlackChannels()
        }
    }, [firstSlackIntegration?.id, loadAllSlackChannels, firstSlackIntegration])

    const handleAdd = (): void => {
        if (selectedType === LOGS_ALERT_NOTIFICATION_TYPE_SLACK) {
            if (!slackChannelValue || !firstSlackIntegration) {
                return
            }
            const parts = slackChannelValue.split('|')
            const channelId = parts[0]
            const channelName = parts[1]?.replace('#', '') ?? channelId

            const notification: PendingLogsAlertNotification = {
                type: LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: firstSlackIntegration.id,
                slackChannelId: channelId,
                slackChannelName: channelName,
            }
            addPendingNotification(notification)
            setSlackChannelValue(null)
        } else {
            if (!webhookUrl) {
                return
            }
            addPendingNotification({ type: selectedType, webhookUrl })
            setWebhookUrl('')
        }
    }

    const getNotificationLabel = (notification: PendingLogsAlertNotification): string => {
        if (notification.type === LOGS_ALERT_NOTIFICATION_TYPE_SLACK) {
            return `Slack: #${notification.slackChannelName ?? 'channel'}`
        }
        if (notification.type === LOGS_ALERT_NOTIFICATION_TYPE_TEAMS) {
            return `Microsoft Teams: ${notification.webhookUrl}`
        }
        return `Webhook: ${notification.webhookUrl}`
    }

    return (
        <div className="flex flex-col gap-2">
            <p className="text-xs text-muted-alt m-0">
                Each destination delivers notifications for all alert events — firing, resolved, and broken.
            </p>
            {(existingHogFunctionsLoading || destinationGroups.length > 0) && (
                <div>
                    {existingHogFunctionsLoading ? (
                        <LemonSkeleton className="h-8" repeat={2} />
                    ) : destinationGroups.length > 0 ? (
                        <div className="space-y-2">
                            {destinationGroups.map((group) => {
                                const detailHogFunctionId =
                                    group.hogFunctions.find((hf) => getHogFunctionEventKind(hf) === 'firing')?.id ??
                                    group.hogFunctions[0]?.id
                                const detailUrl =
                                    alertId && detailHogFunctionId
                                        ? urls.logsAlertNotificationDetail(alertId, detailHogFunctionId)
                                        : undefined
                                return (
                                    <div
                                        key={group.key}
                                        className="flex items-center justify-between border rounded p-2 gap-2"
                                    >
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <span className="text-sm font-medium truncate">
                                                    {resolveGroupLabel(group, slackChannels)}
                                                </span>
                                                <LemonTag type={group.enabled ? 'success' : 'default'} size="small">
                                                    {group.enabled ? 'Active' : 'Paused'}
                                                </LemonTag>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-1 shrink-0">
                                            <LemonButton
                                                size="xsmall"
                                                type="secondary"
                                                to={detailUrl}
                                                disabledReason={
                                                    detailUrl ? undefined : 'Save the alert to view details'
                                                }
                                                data-attr="logs-alert-destination-view"
                                            >
                                                View
                                            </LemonButton>
                                            <LemonButton
                                                icon={<IconTrash />}
                                                size="xsmall"
                                                status="danger"
                                                onClick={() => deleteExistingDestination(group)}
                                                tooltip="Delete notification"
                                            />
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    ) : null}
                </div>
            )}

            {pendingNotifications.length > 0 && (
                <div className="space-y-2">
                    {pendingNotifications.map((notification, index) => (
                        <div
                            key={
                                notification.type === LOGS_ALERT_NOTIFICATION_TYPE_SLACK
                                    ? `slack-${notification.slackChannelId}`
                                    : `${notification.type}-${notification.webhookUrl}`
                            }
                            className="flex items-center justify-between border rounded p-2 gap-2"
                        >
                            <span className="text-sm min-w-0 truncate flex flex-col">
                                {getNotificationLabel(notification)}{' '}
                                <span className="text-muted-alt">
                                    {alertId ? '(saving…)' : '(pending — save alert to apply)'}
                                </span>
                            </span>
                            <LemonButton
                                icon={<IconTrash />}
                                size="xsmall"
                                status="danger"
                                onClick={() => removePendingNotification(index)}
                                tooltip="Remove notification"
                            />
                        </div>
                    ))}
                </div>
            )}

            <div className="space-y-3 border rounded p-3">
                <div className="flex gap-2 items-end">
                    <div className="flex-1">
                        <LemonSelect
                            fullWidth
                            options={LOGS_ALERT_NOTIFICATION_TYPE_OPTIONS}
                            value={selectedType}
                            onChange={(value) => setSelectedType(value)}
                        />
                    </div>
                </div>

                {selectedType === LOGS_ALERT_NOTIFICATION_TYPE_SLACK && (
                    <>
                        {!firstSlackIntegration ? (
                            <SlackNotConfiguredBanner />
                        ) : (
                            <SlackChannelPicker
                                value={slackChannelValue ?? undefined}
                                onChange={(value) => setSlackChannelValue(value)}
                                integration={firstSlackIntegration}
                            />
                        )}
                    </>
                )}

                {selectedType === LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK && (
                    <LemonInput
                        placeholder="https://example.com/webhook"
                        value={webhookUrl}
                        onChange={setWebhookUrl}
                        fullWidth
                    />
                )}

                {selectedType === LOGS_ALERT_NOTIFICATION_TYPE_TEAMS && (
                    <div className="space-y-1">
                        <LemonInput
                            placeholder="https://prod-00.westus.logic.azure.com:443/workflows/..."
                            value={webhookUrl}
                            onChange={setWebhookUrl}
                            fullWidth
                        />
                        <p className="text-xs text-muted-alt m-0">
                            Paste the URL from a Teams "Workflows" (Power Automate) or incoming webhook connector. We
                            send a formatted Adaptive Card to it.
                        </p>
                    </div>
                )}

                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={handleAdd}
                    disabledReason={
                        selectedType === LOGS_ALERT_NOTIFICATION_TYPE_SLACK
                            ? !firstSlackIntegration
                                ? 'Connect Slack first'
                                : !slackChannelValue
                                  ? 'Select a Slack channel'
                                  : undefined
                            : !webhookUrl
                              ? 'Enter a webhook URL'
                              : undefined
                    }
                >
                    Add notification
                </LemonButton>
            </div>
        </div>
    )
}
