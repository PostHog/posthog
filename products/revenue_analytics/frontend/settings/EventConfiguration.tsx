import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { CURRENCY_SYMBOL_TO_EMOJI_MAP, getCurrencySymbol } from 'lib/utils/geography/currency'
import { DataWarehouseManagedViewsetImpactModal } from 'scenes/data-management/managed-viewsets/DataWarehouseManagedViewsetImpactModal'
import { disableDataWarehouseManagedViewsetModalLogic } from 'scenes/data-management/managed-viewsets/disableDataWarehouseManagedViewsetModalLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { RevenueAnalyticsEventItem } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EventConfigurationModal } from './EventConfigurationModal'
import { deleteRevenueEventModalLogic } from './deleteRevenueEventModalLogic'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

export function EventConfiguration({ buttonRef }: { buttonRef?: React.RefObject<HTMLButtonElement> }): JSX.Element {
    const { events } = useValues(revenueAnalyticsSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { views, eventName: eventToBeDeleted } = useValues(deleteRevenueEventModalLogic)

    const { deleteEvent, save } = useActions(revenueAnalyticsSettingsLogic)
    const { openModal } = useActions(disableDataWarehouseManagedViewsetModalLogic({ type: 'EventConfiguration' }))
    const { setEventName: setEventToBeDeleted } = useActions(deleteRevenueEventModalLogic)

    const managedViewsetsEnabled = featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]

    const [modalState, setModalState] = useState<{
        isOpen: boolean
        event?: RevenueAnalyticsEventItem
    }>({ isOpen: false })

    const onDeleteEvent = async (): Promise<boolean> => {
        if (!eventToBeDeleted) {
            return false
        }

        try {
            deleteEvent(eventToBeDeleted)
            save()
            setEventToBeDeleted(null)
            lemonToast.success(`Revenue event "${eventToBeDeleted}" removed successfully`)
            return true
        } catch (error: any) {
            lemonToast.error(`Failed to remove event: ${error.message || 'Unknown error'}`)
        }

        return false
    }

    return (
        <SceneSection
            title="Event Configuration"
            description="PostHog can display revenue data in our Revenue Analytics product from any event. You can configure as many events as you want, and specify the revenue property and currency for each event individually."
        >
            <div className="flex flex-col mb-1 items-end w-full">
                <div className="flex flex-row w-full gap-1 justify-end my-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.RevenueAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={() => setModalState({ isOpen: true })}
                            ref={buttonRef}
                        >
                            Add Revenue Event
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>
            <LemonTable<RevenueAnalyticsEventItem>
                dataSource={events}
                rowKey={(item) => item.eventName}
                emptyState="No event sources configured yet"
                columns={[
                    {
                        key: 'eventName',
                        title: 'Event Name',
                        dataIndex: 'eventName',
                        render: (_, item) => (
                            <div className="flex items-center gap-2">
                                <code className="text-sm font-mono bg-bg-lighter py-1 rounded">{item.eventName}</code>
                            </div>
                        ),
                    },
                    {
                        key: 'revenueProperty',
                        title: 'Revenue Property',
                        dataIndex: 'revenueProperty',
                        render: (_, item) => (
                            <div className="text-sm">
                                {item.revenueProperty ? (
                                    <code className="bg-bg-lighter py-1 rounded text-xs">{item.revenueProperty}</code>
                                ) : (
                                    <span className="text-muted-alt">Not set</span>
                                )}
                            </div>
                        ),
                    },
                    {
                        key: 'currency',
                        title: 'Currency',
                        render: (_, item) => (
                            <div className="text-sm space-y-1">
                                {item.revenueCurrencyProperty.property && (
                                    <div>
                                        <span className="text-muted-alt">Property: </span>
                                        <code className="bg-bg-lighter px-1 rounded text-xs">
                                            {item.revenueCurrencyProperty.property}
                                        </code>
                                    </div>
                                )}
                                {item.revenueCurrencyProperty.static && (
                                    <div>
                                        <span className="text-muted-alt">Static: </span>
                                        <span className="font-medium">
                                            {CURRENCY_SYMBOL_TO_EMOJI_MAP[item.revenueCurrencyProperty.static]}
                                            &nbsp;{item.revenueCurrencyProperty.static}&nbsp;(
                                            {getCurrencySymbol(item.revenueCurrencyProperty.static).symbol})
                                        </span>
                                    </div>
                                )}
                                {item.currencyAwareDecimal && <div className="text-xs text-muted-alt">In cents</div>}
                                {!item.revenueCurrencyProperty.property && !item.revenueCurrencyProperty.static && (
                                    <span className="text-muted-alt">Not configured</span>
                                )}
                            </div>
                        ),
                    },
                    {
                        key: 'properties',
                        title: 'Additional Properties',
                        render: (_, item) => (
                            <div className="text-sm space-y-1">
                                {item.productProperty && (
                                    <div>
                                        <span className="text-muted-alt">Product: </span>
                                        <code className="bg-bg-lighter px-1 rounded text-xs">
                                            {item.productProperty}
                                        </code>
                                    </div>
                                )}
                                {item.couponProperty && (
                                    <div>
                                        <span className="text-muted-alt">Coupon: </span>
                                        <code className="bg-bg-lighter px-1 rounded text-xs">
                                            {item.couponProperty}
                                        </code>
                                    </div>
                                )}
                                {item.subscriptionProperty && (
                                    <div>
                                        <span className="text-muted-alt">Subscription: </span>
                                        <code className="bg-bg-lighter px-1 rounded text-xs">
                                            {item.subscriptionProperty}
                                        </code>
                                        <div className="text-xs text-muted-alt">
                                            Drop subscription after {item.subscriptionDropoffDays} days
                                        </div>
                                        <div className="text-xs text-muted-alt">
                                            Subscription ends on the day{' '}
                                            {item.subscriptionDropoffMode === 'last_event'
                                                ? 'of the last event'
                                                : 'the dropoff period ends'}
                                        </div>
                                    </div>
                                )}
                                {!item.productProperty && !item.couponProperty && !item.subscriptionProperty && (
                                    <span className="text-muted-alt">None configured</span>
                                )}
                            </div>
                        ),
                    },
                    {
                        key: 'actions',
                        title: '',
                        render: (_, item) => (
                            <div className="flex items-center gap-1">
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.RevenueAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        icon={<IconGear />}
                                        onClick={() => setModalState({ isOpen: true, event: item })}
                                        tooltip="Edit event configuration"
                                    />
                                </AccessControlAction>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.RevenueAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        status="danger"
                                        icon={<IconTrash />}
                                        onClick={() => {
                                            if (managedViewsetsEnabled) {
                                                // Show confirmation modal (if feature flag enabled)
                                                setEventToBeDeleted(item.eventName)
                                                openModal('revenue_analytics')
                                            } else {
                                                // Delete directly if feature flag is off
                                                if (confirm('Are you sure you want to remove this event?')) {
                                                    deleteEvent(item.eventName)
                                                    save()
                                                }
                                            }
                                        }}
                                        tooltip="Remove event"
                                    />
                                </AccessControlAction>
                            </div>
                        ),
                    },
                ]}
            />

            {modalState.isOpen &&
                userHasAccess(AccessControlResourceType.RevenueAnalytics, AccessControlLevel.Editor) && (
                    <EventConfigurationModal
                        event={modalState.event}
                        onClose={() => setModalState({ isOpen: false, event: undefined })}
                    />
                )}

            {managedViewsetsEnabled && (
                <DataWarehouseManagedViewsetImpactModal
                    type="EventConfiguration"
                    title={`Remove revenue event "${eventToBeDeleted}"?`}
                    action={onDeleteEvent}
                    confirmText={eventToBeDeleted || ''}
                    views={views}
                    warningItems={[
                        'Remove this event from revenue analytics',
                        "Regenerate all revenue views without this event's data",
                        'Potentially affect existing queries, insights, or dashboards that depend on this data',
                    ]}
                    infoMessage={
                        <>
                            <strong>Important:</strong> The event will no longer be included in revenue calculations for
                            revenue analytics. It'll also trigger re-materialization of all remaining revenue views.
                        </>
                    }
                    viewsActionText="will be removed"
                    confirmButtonText="Yes, remove event"
                />
            )}
        </SceneSection>
    )
}
