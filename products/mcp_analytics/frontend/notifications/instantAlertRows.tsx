import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { IconPlus, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { urlForHogFunction } from 'scenes/hog-functions/list/HogFunctionsList'
import { newNotificationDialogLogic } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import { getNotificationDescription } from 'scenes/hog-functions/list/notificationDescription'
import { NotificationSlackPreview } from 'scenes/hog-functions/sub-templates/NotificationSlackPreview'
import {
    MCP_NOTIFICATION_BUTTON_LABELS,
    MCPMessageField,
    MCPNotificationSubTemplateId,
    mcpNotificationPreviewMessage,
} from 'scenes/hog-functions/sub-templates/sub-templates'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

import { mcpAnalyticsNotificationsLogic, MCPNotificationUseCase } from './mcpAnalyticsNotificationsLogic'
import { mcpNotificationExamplesLogic } from './mcpNotificationExamplesLogic'
import { countSaved, NotificationTypeRow } from './NotificationTypesTable'
import { SavedNotificationRow } from './SavedNotificationRow'

export interface InstantAlertUseCase {
    useCase: MCPNotificationUseCase
    subTemplateId: MCPNotificationSubTemplateId
    icon: JSX.Element
    headline: string
    lead: string
    dialogTitle: string
    /** Shown until the project's own latest event loads; the copy always comes from the template. */
    sample: Record<MCPMessageField, string>
    /** Caption for a preview built from the project's own event. */
    realCaption: string
}

export const INSTANT_ALERT_USE_CASES: InstantAlertUseCase[] = [
    {
        useCase: 'tool-error',
        subTemplateId: 'mcp-tool-error',
        icon: <IconWarning />,
        headline: 'A tool call failed',
        lead: 'Which tool broke, what the agent wanted, and a link to the detail.',
        dialogTitle: 'Notify me about failing tool calls',
        sample: {
            clientName: 'Claude Code',
            serverName: 'acme-mcp',
            intent: 'find out why signups dropped after Tuesday’s release',
            toolName: 'query-events',
        },
        realCaption: 'Your most recent',
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
    } = useValues(mcpAnalyticsNotificationsLogic)
    const { loadNotifications } = useActions(mcpAnalyticsNotificationsLogic)
    const { examples } = useValues(mcpNotificationExamplesLogic)
    const { loadExamples } = useActions(mcpNotificationExamplesLogic)
    const addDisabledReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    useEffect(() => {
        loadNotifications()
        // The previews render sample copy straight away and upgrade to the project's own events when
        // this lands, so there's deliberately no loading state to wait on.
        loadExamples()
    }, [loadNotifications, loadExamples])

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
        const example = examples[config.useCase]
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
                <NotificationSlackPreview
                    message={mcpNotificationPreviewMessage(example ?? config.sample)}
                    buttonLabel={MCP_NOTIFICATION_BUTTON_LABELS[config.subTemplateId]}
                    caption={example ? config.realCaption : 'Example'}
                />
            ),
            savedRows: saved.map((notification) => (
                <NotificationRow key={notification.id} notification={notification} />
            )),
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
