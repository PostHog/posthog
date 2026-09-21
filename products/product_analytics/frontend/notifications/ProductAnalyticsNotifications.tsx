import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCursor, IconPlus, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { ConfirmDeleteButton } from 'lib/components/ConfirmDeleteButton'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { urlForHogFunction } from 'scenes/hog-functions/list/HogFunctionsList'
import { NewNotificationDialog } from 'scenes/hog-functions/list/NewNotificationDialog'
import { newNotificationDialogLogic } from 'scenes/hog-functions/list/newNotificationDialogLogic'
import { getNotificationDescription } from 'scenes/hog-functions/list/notificationDescription'
import { NotificationSlackPreview } from 'scenes/hog-functions/sub-templates/NotificationSlackPreview'
import {
    PA_NOTIFICATION_BUTTON_LABELS,
    PAMessageField,
    PANotificationSubTemplateId,
    paNotificationPreviewMessage,
} from 'scenes/hog-functions/sub-templates/sub-templates'
import { urls } from 'scenes/urls'

import { HogFunctionType, SavedInsightsTabs } from '~/types'

import {
    PANotificationExample,
    productAnalyticsNotificationExamplesLogic,
} from './productAnalyticsNotificationExamplesLogic'
import {
    getPANotificationUseCase,
    PANotificationUseCase,
    productAnalyticsNotificationsLogic,
} from './productAnalyticsNotificationsLogic'
import { ProductAnalyticsRecurringReports } from './ProductAnalyticsRecurringReports'

interface PAUseCaseConfig {
    useCase: PANotificationUseCase
    subTemplateId: PANotificationSubTemplateId
    icon: JSX.Element
    headline: string
    lead: string
    dialogTitle: string
    /** Shown until the project's own latest event loads; the copy always comes from the template. */
    sample: Record<PAMessageField, string>
    /** Caption for a preview built from the project's own event. */
    realCaption: string
}

const USE_CASES: PAUseCaseConfig[] = [
    {
        useCase: 'rageclick',
        subTemplateId: 'pa-rageclick',
        icon: <IconCursor />,
        headline: 'Users are rage clicking',
        lead: 'Which page, which browser, and a link to the session replay.',
        dialogTitle: 'Notify me about rage clicks',
        sample: {
            page: '/pricing',
            browser: 'Chrome',
        },
        realCaption: 'Your most recent',
    },
]

function NotificationRow({ notification }: { notification: HogFunctionType }): JSX.Element {
    const { notificationsLoading, pendingToggleIds } = useValues(productAnalyticsNotificationsLogic)
    const { toggleNotificationEnabled, deleteNotification } = useActions(productAnalyticsNotificationsLogic)

    const description = getNotificationDescription(notification)

    return (
        <div className="flex items-center gap-2 rounded border p-2">
            <HogFunctionIcon src={notification.icon_url} size="small" />
            <div className="min-w-0 flex-1">
                <Link
                    to={urlForHogFunction(notification, urls.savedInsights(SavedInsightsTabs.Notifications))}
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
                data-attr="product-analytics-notification-delete"
            />
        </div>
    )
}

interface UseCaseCardProps {
    config: PAUseCaseConfig
    notifications: HogFunctionType[]
    onAdd: () => void
    addDisabledReason?: string
    /** The project's own latest event for this use case, once it has loaded. */
    example?: PANotificationExample
}

function UseCaseCard({ config, notifications, onAdd, addDisabledReason, example }: UseCaseCardProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3">
            <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-1.5">
                    <span className="mt-0.5 shrink-0 text-muted">{config.icon}</span>
                    <div className="min-w-0">
                        <h3 className="m-0 text-sm font-semibold">{config.headline}</h3>
                        <p className="m-0 text-xs text-muted">{config.lead}</p>
                    </div>
                </div>
                <LemonButton
                    type={notifications.length > 0 ? 'secondary' : 'primary'}
                    size="xsmall"
                    icon={<IconPlus />}
                    onClick={onAdd}
                    disabledReason={addDisabledReason}
                    data-attr={`product-analytics-add-notification-${config.useCase}`}
                >
                    {notifications.length > 0 ? 'Add' : 'Notify me'}
                </LemonButton>
            </div>

            <NotificationSlackPreview
                message={paNotificationPreviewMessage(example ?? config.sample)}
                buttonLabel={PA_NOTIFICATION_BUTTON_LABELS[config.subTemplateId]}
                caption={example ? config.realCaption : 'Example'}
            />

            {notifications.length > 0 && (
                <div className="flex flex-col gap-1">
                    {notifications.map((notification) => (
                        <NotificationRow key={notification.id} notification={notification} />
                    ))}
                </div>
            )}
        </LemonCard>
    )
}

/** Threshold alerts are their own product (per-insight), so this card links out instead of duplicating them. */
function InsightAlertsCard(): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3">
            <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-1.5">
                    <span className="mt-0.5 shrink-0 text-muted">
                        <IconWarning />
                    </span>
                    <div className="min-w-0">
                        <h3 className="m-0 text-sm font-semibold">An insight crosses a threshold</h3>
                        <p className="m-0 text-xs text-muted">
                            Set a threshold on any insight and get a message when it's breached.
                        </p>
                    </div>
                </div>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    to={urls.alerts()}
                    data-attr="product-analytics-notifications-insight-alerts"
                >
                    Manage alerts
                </LemonButton>
            </div>
        </LemonCard>
    )
}

export function ProductAnalyticsNotifications(): JSX.Element {
    const { notifications, notificationsLoaded, notificationsFailed } = useValues(productAnalyticsNotificationsLogic)
    const { loadNotifications } = useActions(productAnalyticsNotificationsLogic)
    const { examples } = useValues(productAnalyticsNotificationExamplesLogic)
    const { loadExamples } = useActions(productAnalyticsNotificationExamplesLogic)
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

    // One dialog logic per use case, called in a fixed order so the hook calls stay stable.
    const { openDialog: openRageclickDialog } = useActions(
        newNotificationDialogLogic({ subTemplateId: 'pa-rageclick', onCreated })
    )
    const openDialogFor: Record<PANotificationSubTemplateId, () => void> = {
        'pa-rageclick': openRageclickDialog,
    }

    // Anything the filters matched but we can't classify still needs a home, so it can't be
    // silently dropped from the list.
    const unclassified = notifications.filter((notification) => !getPANotificationUseCase(notification))

    const instantAlerts = notificationsFailed ? (
        <LemonBanner
            type="error"
            action={{ children: 'Try again', onClick: () => loadNotifications() }}
            data-attr="product-analytics-notifications-load-error"
        >
            We couldn't load your alerts. Please try again in a moment.
        </LemonBanner>
    ) : !notificationsLoaded ? (
        <div className="grid gap-2 md:grid-cols-2">
            {USE_CASES.map((config) => (
                <LemonCard key={config.useCase} hoverEffect={false} className="flex flex-col gap-2 p-3">
                    <LemonSkeleton className="h-4 w-48 max-w-full" />
                    <LemonSkeleton className="h-16 w-full" />
                </LemonCard>
            ))}
        </div>
    ) : (
        <>
            <div className="grid gap-2 md:grid-cols-2">
                {USE_CASES.map((config) => (
                    <UseCaseCard
                        key={config.useCase}
                        config={config}
                        notifications={notifications.filter(
                            (notification) => getPANotificationUseCase(notification) === config.useCase
                        )}
                        onAdd={openDialogFor[config.subTemplateId]}
                        addDisabledReason={addDisabledReason ?? undefined}
                        example={examples[config.useCase]}
                    />
                ))}
                <InsightAlertsCard />
            </div>

            {unclassified.length > 0 && (
                <LemonCard hoverEffect={false} className="flex flex-col gap-1 p-3">
                    <h3 className="m-0 text-sm font-semibold">Other product analytics alerts</h3>
                    {unclassified.map((notification) => (
                        <NotificationRow key={notification.id} notification={notification} />
                    ))}
                </LemonCard>
            )}
        </>
    )

    return (
        <div className="flex flex-col gap-6" data-attr="product-analytics-notifications">
            <ProductAnalyticsRecurringReports />

            <section className="flex flex-col gap-2">
                <h2 className="m-0 text-base font-semibold">Instant alerts</h2>
                <p className="m-0 text-sm text-muted">
                    One message per event, for the things you'd want to hear about the moment they happen. A busy site
                    can send a lot of these.
                </p>
                {instantAlerts}
            </section>

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
