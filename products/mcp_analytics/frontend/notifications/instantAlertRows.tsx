import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { IconPlus, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { urlForHogFunction } from 'scenes/hog-functions/list/HogFunctionsList'
import { DESTINATION_OPTIONS, newNotificationDialogLogic } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import { getNotificationDescription } from 'scenes/hog-functions/list/notificationDescription'
import { MCPNotificationSubTemplateId } from 'scenes/hog-functions/sub-templates/sub-templates'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

import { mcpAnalyticsNotificationsLogic, MCPNotificationUseCase } from './mcpAnalyticsNotificationsLogic'
import { NotificationDetails } from './NotificationDetails'
import { countSaved, NotificationTypeRow } from './NotificationTypeCards'
import { SavedNotificationRow } from './SavedNotificationRow'

export interface InstantAlertUseCase {
    useCase: MCPNotificationUseCase
    subTemplateId: MCPNotificationSubTemplateId
    icon: JSX.Element
    headline: string
    lead: string
    dialogTitle: string
    covers: string[]
}

const ALERT_DESTINATIONS = DESTINATION_OPTIONS.map((option) => ({
    key: option.templateId,
    label: option.label,
    icon: <img src={option.iconUrl} alt="" />,
}))

export const INSTANT_ALERT_USE_CASES: InstantAlertUseCase[] = [
    {
        useCase: 'tool-error',
        subTemplateId: 'mcp-tool-error',
        icon: <IconWarning />,
        headline: 'Failed tool call alerting',
        lead: 'An alert that posts a message to your team each time a tool call fails.',
        dialogTitle: 'Notify me about failing tool calls',
        covers: [
            'Which tool failed and which harness called it',
            'What the agent was trying to do',
            'A link to the tool in PostHog',
        ],
    },
]

function NotificationRow({ notification }: { notification: HogFunctionType }): JSX.Element {
    const { notificationsLoading, pendingToggleIds } = useValues(mcpAnalyticsNotificationsLogic)
    const { toggleNotificationEnabled, deleteNotification } = useActions(mcpAnalyticsNotificationsLogic)
    const { searchParams } = useValues(router)

    return (
        <SavedNotificationRow
            icon={<HogFunctionIcon src={notification.icon_url} size="small" />}
            name={notification.name}
            to={urlForHogFunction(
                notification,
                // Carry the scene's shared params (date range) so returning doesn't reset them
                combineUrl(urls.mcpAnalyticsNotifications(), searchParams).url
            )}
            summary={getNotificationDescription(notification)}
            enabled={notification.enabled}
            onToggle={(enabled) => toggleNotificationEnabled(notification.id, enabled)}
            toggleLoading={!!pendingToggleIds[notification.id]}
            // Refresh in flight: a mutation started now could be clobbered by the stale response
            toggleDisabled={notificationsLoading}
            onDelete={() => deleteNotification(notification)}
            deleteDisabledReason={
                notificationsLoading
                    ? 'Refreshing notifications…'
                    : pendingToggleIds[notification.id]
                      ? 'Waiting for the enable/disable update to finish…'
                      : undefined
            }
            deleteDataAttr="mcp-analytics-notification-delete"
        />
    )
}

export interface InstantAlertRows {
    rows: NotificationTypeRow[]
    loaded: boolean
    failed: boolean
    reload: () => void
}

export function useInstantAlertRows(): InstantAlertRows {
    const {
        notificationsByUseCase,
        unclassifiedNotifications,
        notificationsLoaded,
        notificationsFailed,
        notificationsTruncated,
        notificationsLoading,
        pendingToggleIds,
    } = useValues(mcpAnalyticsNotificationsLogic)
    const { loadNotifications, toggleNotificationEnabled } = useActions(mcpAnalyticsNotificationsLogic)
    const { searchParams } = useValues(router)
    const addDisabledReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    useEffect(() => {
        loadNotifications()
    }, [loadNotifications])

    // One dialog logic per use case, called in a fixed order so the hook calls stay stable.
    const { openDialog: openToolErrorDialog } = useActions(
        newNotificationDialogLogic({ subTemplateId: 'mcp-tool-error', onCreated: loadNotifications })
    )
    const openDialogFor: Record<MCPNotificationSubTemplateId, () => void> = {
        'mcp-tool-error': openToolErrorDialog,
    }

    const rows: NotificationTypeRow[] = INSTANT_ALERT_USE_CASES.map((config) => {
        const saved = notificationsByUseCase[config.useCase] ?? []
        // A cut list may hide a match past the page limit, so it never gets a primary "Set up".
        const mayExist = saved.length > 0 || notificationsTruncated
        const [first] = saved
        return {
            key: `alert-${config.useCase}`,
            icon: config.icon,
            headline: config.headline,
            lead: config.lead,
            cadence: 'instant',
            saved: notificationsLoaded ? countSaved(saved, notificationsTruncated) : undefined,
            action: (
                <LemonButton
                    type={mayExist ? 'secondary' : 'primary'}
                    size="small"
                    icon={mayExist ? <IconPlus /> : undefined}
                    onClick={openDialogFor[config.subTemplateId]}
                    disabledReason={addDisabledReason ?? undefined}
                    data-attr={`mcp-analytics-add-notification-${config.useCase}`}
                >
                    {mayExist ? 'Add' : 'Set up'}
                </LemonButton>
            ),
            preview: (
                <NotificationDetails
                    covers={config.covers}
                    destinations={ALERT_DESTINATIONS}
                    activeDestination={first?.enabled ? first.template?.id : undefined}
                />
            ),
            // ponytail: a type holds one alert; older projects with extras toggle them together and edit the newest.
            setup: first
                ? {
                      enabled: saved.some((notification) => notification.enabled),
                      summary: getNotificationDescription(first),
                      editTo: urlForHogFunction(first, combineUrl(urls.mcpAnalyticsNotifications(), searchParams).url),
                      onToggle: (enabled) =>
                          saved.forEach((notification) => toggleNotificationEnabled(notification.id, enabled)),
                      toggleLoading: saved.some((notification) => pendingToggleIds[notification.id]),
                      // A refresh in flight could clobber a toggle started now.
                      toggleDisabled: notificationsLoading,
                  }
                : undefined,
            savedRows: [],
        }
    })

    const unclassified = unclassifiedNotifications
    if (unclassified.length > 0) {
        rows.push({
            key: 'alert-other',
            icon: <IconWarning />,
            headline: 'Other MCP alerts',
            lead: 'Alerts on MCP events that do not match a template above.',
            saved: countSaved(unclassified, notificationsTruncated),
            savedRows: unclassified.map((notification) => (
                <NotificationRow key={notification.id} notification={notification} />
            )),
        })
    }

    return { rows, loaded: notificationsLoaded, failed: notificationsFailed, reload: loadNotifications }
}
