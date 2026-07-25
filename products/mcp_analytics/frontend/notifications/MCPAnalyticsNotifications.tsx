import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { IconMCP, IconPlus, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { ConfirmDeleteButton } from 'lib/components/ConfirmDeleteButton'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { urlForHogFunction } from 'scenes/hog-functions/list/HogFunctionsList'
import { NewNotificationDialog } from 'scenes/hog-functions/list/NewNotificationDialog'
import { newNotificationDialogLogic } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import { getNotificationDescription } from 'scenes/hog-functions/list/notificationDescription'
import {
    MCP_NOTIFICATION_BUTTON_LABELS,
    MCPMessageField,
    mcpNotificationPreviewMessage,
} from 'scenes/hog-functions/sub-templates/sub-templates'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

import {
    getMCPNotificationUseCase,
    mcpAnalyticsNotificationsLogic,
    MCPNotificationUseCase,
} from './mcpAnalyticsNotificationsLogic'
import { MCPNotificationExample, mcpNotificationExamplesLogic } from './mcpNotificationExamplesLogic'
import { MCPNotificationPreview } from './MCPNotificationPreview'

type MCPNotificationSubTemplateId = 'mcp-missing-capability' | 'mcp-tool-error'

interface MCPUseCaseConfig {
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

const USE_CASES: MCPUseCaseConfig[] = [
    {
        useCase: 'missing-capability',
        subTemplateId: 'mcp-missing-capability',
        icon: <IconMCP className="text-lg" />,
        headline: "Agents asked for something your server can't do",
        lead: "Their own words, as they asked for it. The closest thing you'll get to a roadmap.",
        dialogTitle: 'Notify me about missing capabilities',
        sample: {
            clientName: 'Cursor',
            serverName: 'acme-mcp',
            intent: 'export the signups dashboard to PDF and email it to the team every Monday',
            toolName: '',
        },
        realCaption: 'Your most recent one',
    },
    {
        useCase: 'tool-error',
        subTemplateId: 'mcp-tool-error',
        icon: <IconWarning className="text-lg" />,
        headline: 'A tool call failed',
        lead: 'Which tool broke, what the agent was trying to do, and a link straight to the detail.',
        dialogTitle: 'Notify me about failing tool calls',
        sample: {
            clientName: 'Claude Code',
            serverName: 'acme-mcp',
            intent: 'find out why signups dropped after Tuesday’s release',
            toolName: 'query-events',
        },
        realCaption: 'Your most recent failure',
    },
]

function NotificationRow({ notification }: { notification: HogFunctionType }): JSX.Element {
    const { notificationsLoading, pendingToggleIds } = useValues(mcpAnalyticsNotificationsLogic)
    const { toggleNotificationEnabled, deleteNotification } = useActions(mcpAnalyticsNotificationsLogic)
    const { searchParams } = useValues(router)

    const description = getNotificationDescription(notification)

    return (
        <div className="flex items-center gap-2 rounded border p-2">
            <HogFunctionIcon src={notification.icon_url} size="small" />
            <div className="min-w-0 flex-1">
                <Link
                    to={urlForHogFunction(
                        notification,
                        // Carry the scene's shared params (date range) so returning doesn't reset them
                        combineUrl(urls.mcpAnalyticsNotifications(), searchParams).url
                    )}
                    className="font-medium truncate"
                >
                    {notification.name}
                </Link>
                {description ? <div className="text-xs text-muted truncate">{description}</div> : null}
            </div>
            <LemonSwitch
                checked={notification.enabled}
                onChange={() => toggleNotificationEnabled(notification.id, !notification.enabled)}
                loading={!!pendingToggleIds[notification.id]}
                // Refresh in flight: a mutation started now could be clobbered by the stale response
                disabled={notificationsLoading}
                aria-label={`Enable ${notification.name}`}
            />
            <ConfirmDeleteButton
                onDelete={() => deleteNotification(notification)}
                disabledReason={
                    notificationsLoading
                        ? 'Refreshing notifications…'
                        : pendingToggleIds[notification.id]
                          ? 'Waiting for the enable/disable update to finish…'
                          : undefined
                }
                data-attr="mcp-analytics-notification-delete"
            />
        </div>
    )
}

interface UseCaseCardProps {
    config: MCPUseCaseConfig
    notifications: HogFunctionType[]
    onAdd: () => void
    addDisabledReason?: string
    /** The project's own latest event for this use case, once it has loaded. */
    example?: MCPNotificationExample
}

function UseCaseCard({ config, notifications, onAdd, addDisabledReason, example }: UseCaseCardProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3">
            <div className="flex items-start gap-2">
                <span className="mt-0.5 shrink-0 text-muted">{config.icon}</span>
                <div className="min-w-0">
                    <h3 className="m-0 text-base font-semibold">{config.headline}</h3>
                    <p className="m-0 text-sm text-muted">{config.lead}</p>
                </div>
            </div>

            <MCPNotificationPreview
                message={mcpNotificationPreviewMessage(config.subTemplateId, example ?? config.sample)}
                buttonLabel={MCP_NOTIFICATION_BUTTON_LABELS[config.subTemplateId]}
                caption={example ? config.realCaption : 'Example'}
            />

            {notifications.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    {notifications.map((notification) => (
                        <NotificationRow key={notification.id} notification={notification} />
                    ))}
                </div>
            )}

            <div>
                <LemonButton
                    type={notifications.length > 0 ? 'secondary' : 'primary'}
                    size="small"
                    icon={<IconPlus />}
                    onClick={onAdd}
                    disabledReason={addDisabledReason}
                    data-attr={`mcp-analytics-add-notification-${config.useCase}`}
                >
                    {notifications.length > 0 ? 'Add another destination' : 'Notify me'}
                </LemonButton>
            </div>
        </LemonCard>
    )
}

export function MCPAnalyticsNotifications(): JSX.Element {
    const { notifications, notificationsLoaded, notificationsFailed } = useValues(mcpAnalyticsNotificationsLogic)
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

    const onCreated = (): void => {
        loadNotifications()
    }

    // One dialog logic per use case, in a fixed order so the hook calls stay stable.
    const { openDialog: openMissingCapabilityDialog } = useActions(
        newNotificationDialogLogic({ subTemplateId: 'mcp-missing-capability', onCreated })
    )
    const { openDialog: openToolErrorDialog } = useActions(
        newNotificationDialogLogic({ subTemplateId: 'mcp-tool-error', onCreated })
    )
    const openDialogFor: Record<MCPNotificationSubTemplateId, () => void> = {
        'mcp-missing-capability': openMissingCapabilityDialog,
        'mcp-tool-error': openToolErrorDialog,
    }

    if (notificationsFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadNotifications() }}
                data-attr="mcp-analytics-notifications-load-error"
            >
                We couldn't load your MCP notifications. Please try again in a moment.
            </LemonBanner>
        )
    }

    if (!notificationsLoaded) {
        return (
            <div className="flex flex-col gap-3" data-attr="mcp-analytics-notifications">
                {USE_CASES.map((config) => (
                    <LemonCard key={config.useCase} hoverEffect={false} className="flex flex-col gap-3">
                        <LemonSkeleton className="h-4 w-64 max-w-full" />
                        <LemonSkeleton className="h-20 w-full" />
                        <LemonSkeleton className="h-8 w-28" />
                    </LemonCard>
                ))}
            </div>
        )
    }

    // Anything the filters matched but we can't classify still needs a home, so it can't be
    // silently dropped from the list.
    const unclassified = notifications.filter((notification) => !getMCPNotificationUseCase(notification))

    return (
        <div className="flex flex-col gap-3" data-attr="mcp-analytics-notifications">
            <p className="m-0 text-sm text-muted">
                Pick a moment worth interrupting you for. Each one posts to Slack, Discord, Microsoft Teams, or any
                webhook.
            </p>

            {USE_CASES.map((config) => (
                <UseCaseCard
                    key={config.useCase}
                    config={config}
                    notifications={notifications.filter(
                        (notification) => getMCPNotificationUseCase(notification) === config.useCase
                    )}
                    onAdd={openDialogFor[config.subTemplateId]}
                    addDisabledReason={addDisabledReason ?? undefined}
                    example={examples[config.useCase]}
                />
            ))}

            {unclassified.length > 0 && (
                <LemonCard hoverEffect={false} className="flex flex-col gap-2">
                    <h3 className="m-0 text-base font-semibold">Other MCP notifications</h3>
                    {unclassified.map((notification) => (
                        <NotificationRow key={notification.id} notification={notification} />
                    ))}
                </LemonCard>
            )}

            {USE_CASES.map((config) => (
                <NewNotificationDialog
                    key={config.subTemplateId}
                    subTemplateId={config.subTemplateId}
                    onCreated={onCreated}
                    title={config.dialogTitle}
                />
            ))}
        </div>
    )
}
