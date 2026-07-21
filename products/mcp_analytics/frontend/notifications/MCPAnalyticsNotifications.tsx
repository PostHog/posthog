import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill-primitives'

import { ConfirmDeleteButton } from 'lib/components/ConfirmDeleteButton'
import { MailHog } from 'lib/components/hedgehogs'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { urlForHogFunction } from 'scenes/hog-functions/list/HogFunctionsList'
import { NewNotificationDialog } from 'scenes/hog-functions/list/NewNotificationDialog'
import { newNotificationDialogLogic } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import { getNotificationDescription } from 'scenes/hog-functions/list/notificationDescription'
import { urls } from 'scenes/urls'

import {
    getMCPNotificationUseCase,
    mcpAnalyticsNotificationsLogic,
    MCPNotificationUseCase,
} from './mcpAnalyticsNotificationsLogic'

const USE_CASE_LABELS: Record<MCPNotificationUseCase, string> = {
    'missing-capability': 'Missing capability',
    'tool-error': 'Tool call failed',
}

export function MCPAnalyticsNotifications(): JSX.Element {
    const { notifications, notificationsLoading, notificationsLoaded, notificationsFailed, pendingToggleIds } =
        useValues(mcpAnalyticsNotificationsLogic)
    const { searchParams } = useValues(router)
    const { loadNotifications, toggleNotificationEnabled, deleteNotification } =
        useActions(mcpAnalyticsNotificationsLogic)
    const addDisabledReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    useEffect(() => {
        loadNotifications()
    }, [loadNotifications])

    const onCreated = (): void => {
        loadNotifications()
    }
    const missingCapabilityDialogLogic = newNotificationDialogLogic({
        subTemplateId: 'mcp-missing-capability',
        onCreated,
    })
    const toolErrorDialogLogic = newNotificationDialogLogic({
        subTemplateId: 'mcp-tool-error',
        onCreated,
    })
    const { openDialog: openMissingCapabilityDialog } = useActions(missingCapabilityDialogLogic)
    const { openDialog: openToolErrorDialog } = useActions(toolErrorDialogLogic)

    const renderAddNotificationButton = (type: 'primary' | 'secondary', size?: 'small'): JSX.Element => (
        <DropdownMenu>
            <DropdownMenuTrigger
                disabled={!!addDisabledReason}
                render={
                    <LemonButton
                        type={type}
                        size={size}
                        icon={<IconPlus />}
                        disabledReason={addDisabledReason ?? undefined}
                        data-attr="mcp-analytics-add-notification"
                    >
                        Add notification
                    </LemonButton>
                }
            />
            <DropdownMenuContent align="end" className="w-auto">
                <DropdownMenuItem onClick={openMissingCapabilityDialog}>
                    <div className="min-w-0">
                        <div>Agents asked for something your server can't do</div>
                        <div className="text-xs text-muted">Their verbatim intent, delivered as your MCP roadmap.</div>
                    </div>
                </DropdownMenuItem>
                <DropdownMenuItem onClick={openToolErrorDialog}>
                    <div className="min-w-0">
                        <div>A tool call failed</div>
                        <div className="text-xs text-muted">
                            The failing tool, the agent's intent, and a link to the tool detail.
                        </div>
                    </div>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )

    let content: JSX.Element

    if (!notificationsLoaded) {
        content = (
            <div className="flex flex-col gap-1.5">
                {Array.from({ length: 2 }).map((_, i) => (
                    <div key={i} className="flex items-center gap-2 rounded border p-2 h-12">
                        <LemonSkeleton className="h-[30px] w-[30px] rounded shrink-0" />
                        <div className="flex-1 min-w-0 flex flex-col gap-1">
                            <LemonSkeleton className="h-3 w-40 max-w-full" />
                            <LemonSkeleton className="h-2 w-28 max-w-full" />
                        </div>
                        <LemonSkeleton className="h-5 w-9 rounded-full shrink-0" />
                    </div>
                ))}
            </div>
        )
    } else if (notificationsFailed) {
        content = (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadNotifications() }}
                data-attr="mcp-analytics-notifications-load-error"
            >
                We couldn't load your MCP notifications. Please try again in a moment.
            </LemonBanner>
        )
    } else if (notifications.length === 0) {
        content = (
            <section className="flex flex-col items-center gap-5 px-6 py-12 text-center">
                <MailHog className="h-32 w-auto" />
                <div className="flex flex-col gap-1.5 max-w-md">
                    <h3 className="m-0 text-base font-semibold">Get notified the moment it matters</h3>
                    <p className="m-0 text-sm text-muted">
                        Send missing capabilities and failing tool calls straight to Slack, Discord, Microsoft Teams, or
                        any webhook.
                    </p>
                </div>
                {renderAddNotificationButton('primary')}
            </section>
        )
    } else {
        content = (
            <>
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="m-0 text-sm text-muted flex-1 min-w-0">
                        Hear about these moments in Slack, Discord, Microsoft Teams, or any webhook.
                    </p>
                    {renderAddNotificationButton('secondary', 'small')}
                </div>
                <div className="flex flex-col gap-1.5">
                    {notifications.map((fn) => {
                        const notificationDescription = getNotificationDescription(fn)
                        const useCase = getMCPNotificationUseCase(fn)

                        return (
                            <div key={fn.id} className="flex items-center gap-2 rounded border p-2">
                                <HogFunctionIcon src={fn.icon_url} size="small" />
                                <div className="flex-1 min-w-0">
                                    <Link
                                        to={urlForHogFunction(
                                            fn,
                                            // Carry the scene's shared params (date range) so returning doesn't reset them
                                            combineUrl(urls.mcpAnalyticsNotifications(), searchParams).url
                                        )}
                                        className="font-medium truncate"
                                    >
                                        {fn.name}
                                    </Link>
                                    {notificationDescription ? (
                                        <div className="text-xs text-muted truncate">{notificationDescription}</div>
                                    ) : null}
                                </div>
                                <LemonTag type="muted" size="small" className="shrink-0">
                                    {useCase ? USE_CASE_LABELS[useCase] : 'MCP notification'}
                                </LemonTag>
                                <LemonSwitch
                                    checked={fn.enabled}
                                    onChange={() => toggleNotificationEnabled(fn.id, !fn.enabled)}
                                    loading={!!pendingToggleIds[fn.id]}
                                    // Refresh in flight: a mutation started now could be clobbered by the stale response
                                    disabled={notificationsLoading}
                                />
                                <ConfirmDeleteButton
                                    onDelete={() => deleteNotification(fn)}
                                    disabledReason={
                                        notificationsLoading
                                            ? 'Refreshing notifications…'
                                            : pendingToggleIds[fn.id]
                                              ? 'Waiting for the enable/disable update to finish…'
                                              : undefined
                                    }
                                    data-attr="mcp-analytics-notification-delete"
                                />
                            </div>
                        )
                    })}
                </div>
            </>
        )
    }

    return (
        <div className="flex flex-col gap-3" data-attr="mcp-analytics-notifications">
            {content}
            <NewNotificationDialog
                subTemplateId="mcp-missing-capability"
                onCreated={onCreated}
                title="Notify me about missing capabilities"
            />
            <NewNotificationDialog
                subTemplateId="mcp-tool-error"
                onCreated={onCreated}
                title="Notify me about failing tool calls"
            />
        </div>
    )
}
