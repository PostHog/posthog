import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect, LemonSwitch, Link } from '@posthog/lemon-ui'

import { CurrencyDropdown } from 'lib/components/BaseCurrency/CurrencyDropdown'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { RevenueAnalyticsEventItem, SubscriptionDropoffMode } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

interface EventConfigurationModalProps {
    event?: RevenueAnalyticsEventItem
    onClose: () => void
}

export function EventConfigurationModal({ event, onClose }: EventConfigurationModalProps): JSX.Element | null {
    const { baseCurrency } = useValues(teamLogic)
    const { events, saveEventsDisabledReason } = useValues(revenueAnalyticsSettingsLogic)
    const {
        addEvent,
        deleteEvent,
        updateEventRevenueProperty,
        updateEventCurrencyProperty,
        updateEventCurrencyAwareDecimalProperty,
        updateEventProductProperty,
        updateEventCouponProperty,
        updateEventSubscriptionProperty,
        updateEventSubscriptionDropoffDays,
        updateEventSubscriptionDropoffMode,
        save,
    } = useActions(revenueAnalyticsSettingsLogic)

    // Track the name of the event we care about
    const [eventName, setEventName] = useState<string | null>(() => event?.eventName ?? null)
    const [originalEvent] = useState<RevenueAnalyticsEventItem | null>(() => (event ? { ...event } : null))

    // Don't show the modal if the user doesn't have access to the revenue analytics resource
    if (!userHasAccess(AccessControlResourceType.RevenueAnalytics, AccessControlLevel.Editor)) {
        onClose()
        return null
    }

    // Get current event data from store
    const currentEvent = eventName ? events.find((e) => e.eventName === eventName) : null

    const handleSave = (): void => {
        save()
        onClose()
    }

    const handleClose = (): void => {
        // If we had an original event and we're closing, then let's rollback to the original event state
        if (originalEvent) {
            deleteEvent(originalEvent.eventName)
            addEvent(originalEvent.eventName, baseCurrency)

            updateEventRevenueProperty(originalEvent.eventName, originalEvent.revenueProperty || '')
            updateEventCurrencyProperty(originalEvent.eventName, originalEvent.revenueCurrencyProperty)
            updateEventCurrencyAwareDecimalProperty(originalEvent.eventName, originalEvent.currencyAwareDecimal)
            updateEventProductProperty(originalEvent.eventName, originalEvent.productProperty || '')
            updateEventCouponProperty(originalEvent.eventName, originalEvent.couponProperty || '')
            updateEventSubscriptionProperty(originalEvent.eventName, originalEvent.subscriptionProperty || '')
            updateEventSubscriptionDropoffDays(originalEvent.eventName, originalEvent.subscriptionDropoffDays)
            updateEventSubscriptionDropoffMode(originalEvent.eventName, originalEvent.subscriptionDropoffMode)
        } else if (eventName) {
            deleteEvent(eventName)
        }

        onClose()
    }

    return (
        <LemonModal isOpen onClose={handleClose} width={800}>
            <LemonModal.Header>
                <h3>{originalEvent ? `Edit Event: ${originalEvent?.eventName}` : 'Add Revenue Event'}</h3>
            </LemonModal.Header>

            <LemonModal.Content>
                <div className="space-y-4">
                    {!originalEvent && (
                        <LemonBanner type="info" className="text-sm">
                            <strong>How it works:</strong> PostHog will track this event and use these properties for
                            revenue calculations. You can always modify these settings later.
                        </LemonBanner>
                    )}

                    {/* Event Selection */}
                    <div className="space-y-1">
                        <label className="text-sm font-semibold">
                            Event Name <span className="text-danger">*</span>
                        </label>
                        {currentEvent ? (
                            <div className="bg-bg-light rounded-lg">
                                <div className="flex items-center gap-2">
                                    <code className="text-sm font-mono bg-bg-lighter py-1 rounded">
                                        {currentEvent.eventName}
                                    </code>
                                </div>
                                <p className="text-xs text-muted-alt mt-1">
                                    Event name cannot be changed when editing. You can delete and add a new event
                                    instead.
                                </p>
                            </div>
                        ) : (
                            <TaxonomicPopover
                                type="primary"
                                groupType={TaxonomicFilterGroupType.CustomEvents}
                                onChange={(selectedEventName: string) => {
                                    if (selectedEventName) {
                                        // For new events, create the event immediately
                                        addEvent(selectedEventName, baseCurrency)
                                        setEventName(selectedEventName)
                                    }
                                }}
                                value={''}
                                placeholder="Select or type an event name"
                            />
                        )}
                    </div>

                    <hr />

                    {/* Revenue Property */}
                    <div className="space-y-1">
                        <label className="text-sm font-semibold">
                            Revenue Property <span className="text-danger">*</span>
                        </label>
                        <TaxonomicPopover
                            showNumericalPropsOnly
                            groupType={TaxonomicFilterGroupType.EventProperties}
                            onChange={(propertyName) => {
                                if (currentEvent?.eventName) {
                                    updateEventRevenueProperty(currentEvent.eventName, propertyName || '')
                                }
                            }}
                            value={currentEvent?.revenueProperty || undefined}
                            placeholder="Select the property that contains revenue amount"
                            disabledReason={
                                !currentEvent?.eventName
                                    ? 'Select an event name first'
                                    : currentEvent?.eventName === '$pageview' ||
                                        currentEvent?.eventName === '$autocapture'
                                      ? 'Built-in events must use revenue'
                                      : undefined
                            }
                        />
                        <p className="text-xs text-muted-alt">
                            Choose the property that tracks the amount of revenue generated by this event.
                        </p>
                        <p className="text-xs text-muted-alt">
                            NOTE: We only display <strong>numerical</strong> properties in here. If you're not seeing
                            your property here, make sure it's properly set as numeric in the{' '}
                            <Link to={urls.propertyDefinitions()} target="_blank">
                                Property Definitions
                            </Link>{' '}
                            page.
                        </p>
                    </div>

                    <hr />

                    {/* Currency Configuration */}
                    <h4 className="text-md font-semibold">Currency Configuration</h4>
                    <p className="text-sm text-muted-alt">
                        Choose how to handle currency for this event. You can either use a dynamic property that
                        contains the 3-letter currency code for each event, or set a static currency that applies to all
                        events of this type.
                    </p>

                    <div className="flex flex-col md:flex-row gap-4 items-center">
                        <div className="space-y-1 flex-1">
                            <label className="text-sm font-medium">Dynamic Currency Property</label>
                            <TaxonomicPopover
                                groupType={TaxonomicFilterGroupType.EventProperties}
                                onChange={(propertyName) => {
                                    if (currentEvent?.eventName) {
                                        updateEventCurrencyProperty(currentEvent.eventName, {
                                            property: propertyName || '',
                                        })
                                    }
                                }}
                                value={currentEvent?.revenueCurrencyProperty.property || undefined}
                                placeholder="Select property for dynamic currency"
                                disabledReason={!currentEvent?.eventName ? 'Select an event name first' : undefined}
                            />
                        </div>

                        <div className="flex items-center justify-center px-4 py-2 md:py-4">
                            <div className="bg-border-light rounded-full px-3 py-1">
                                <span className="text-xs font-bold text-muted tracking-wider">OR</span>
                            </div>
                        </div>

                        <div className="space-y-1 flex-1">
                            <label className="text-sm font-medium">Static Currency</label>
                            <div className={!currentEvent?.eventName ? 'opacity-50 pointer-events-none' : ''}>
                                <CurrencyDropdown
                                    onChange={(currency) => {
                                        if (currentEvent?.eventName) {
                                            updateEventCurrencyProperty(currentEvent.eventName, {
                                                static: currency || '',
                                            })
                                        }
                                    }}
                                    value={currentEvent?.revenueCurrencyProperty.static || null}
                                    disabledReason={!currentEvent?.eventName ? 'Select an event name first' : undefined}
                                />
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <LemonSwitch
                            checked={currentEvent?.currencyAwareDecimal || false}
                            onChange={(checked) => {
                                if (currentEvent?.eventName) {
                                    updateEventCurrencyAwareDecimalProperty(currentEvent.eventName, checked)
                                }
                            }}
                            disabledReason={!currentEvent?.eventName ? 'Select an event name first' : undefined}
                        />
                        <div className="flex items-center gap-1">
                            <span className="text-sm font-medium">Values are in cents</span>
                            <Tooltip title="Enable this if your revenue values are in the smallest unit of currency (e.g. cents for USD, yen for JPY). We will divide by the smallest unit (e.g. 100 for USD, 1 for JPY)">
                                <IconInfo className="w-4 h-4 text-muted-alt" />
                            </Tooltip>
                        </div>
                    </div>
                </div>

                <hr />

                {/* Advanced Properties */}
                <div className="space-y-3">
                    <h4 className="text-md font-semibold">Advanced Properties (Optional)</h4>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-1">
                            <label className="text-sm font-medium">Product Property</label>
                            <TaxonomicPopover
                                groupType={TaxonomicFilterGroupType.EventProperties}
                                onChange={(propertyName) => {
                                    if (currentEvent?.eventName) {
                                        updateEventProductProperty(currentEvent.eventName, propertyName || '')
                                    }
                                }}
                                value={currentEvent?.productProperty || undefined}
                                placeholder="Select product property"
                                disabledReason={!currentEvent?.eventName ? 'Select an event name first' : undefined}
                            />
                            <p className="text-xs text-muted-alt">
                                Track which product was responsible for generating this revenue event
                            </p>
                        </div>

                        <div className="space-y-1">
                            <label className="text-sm font-medium">Coupon Property</label>
                            <TaxonomicPopover
                                groupType={TaxonomicFilterGroupType.EventProperties}
                                onChange={(propertyName) => {
                                    if (currentEvent?.eventName) {
                                        updateEventCouponProperty(currentEvent.eventName, propertyName || '')
                                    }
                                }}
                                value={currentEvent?.couponProperty || undefined}
                                placeholder="Select coupon property"
                                disabledReason={!currentEvent?.eventName ? 'Select an event name first' : undefined}
                            />
                            <p className="text-xs text-muted-alt">
                                Track which coupon was applied to this revenue event
                            </p>
                        </div>
                    </div>
                </div>

                <hr />

                {/* Subscription Configuration */}
                <div className="space-y-3">
                    <h4 className="text-md font-semibold">Subscription Tracking</h4>

                    <div className="space-y-3">
                        <div className="space-y-1">
                            <label className="text-sm font-medium">Subscription Property</label>
                            <TaxonomicPopover
                                groupType={TaxonomicFilterGroupType.EventProperties}
                                onChange={(propertyName) => {
                                    if (currentEvent?.eventName) {
                                        updateEventSubscriptionProperty(currentEvent.eventName, propertyName || '')
                                    }
                                }}
                                value={currentEvent?.subscriptionProperty || undefined}
                                placeholder="Select subscription property (optional)"
                                disabledReason={!currentEvent?.eventName ? 'Select an event name first' : undefined}
                            />
                            <p className="text-xs text-muted-alt">
                                Track subscription information for ARPU and LTV calculations. Recommended for better
                                revenue insights.
                            </p>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-1">
                                <label className="text-sm font-medium">Dropoff Days</label>
                                <LemonInput
                                    type="number"
                                    min={1}
                                    max={365}
                                    value={currentEvent?.subscriptionDropoffDays || 45}
                                    onChange={(value) => {
                                        if (currentEvent?.eventName) {
                                            updateEventSubscriptionDropoffDays(
                                                currentEvent.eventName,
                                                Number(value) || 45
                                            )
                                        }
                                    }}
                                    disabledReason={!currentEvent?.eventName ? 'Select an event name first' : undefined}
                                />
                                <p className="text-xs text-muted-alt">
                                    Days to consider subscription active after last event
                                </p>
                            </div>

                            <div className="space-y-1">
                                <label className="text-sm font-medium">Dropoff Mode</label>
                                <LemonSelect<SubscriptionDropoffMode>
                                    value={currentEvent?.subscriptionDropoffMode || 'last_event'}
                                    onChange={(value) => {
                                        if (currentEvent?.eventName && value) {
                                            updateEventSubscriptionDropoffMode(currentEvent.eventName, value)
                                        }
                                    }}
                                    disabledReason={!currentEvent?.eventName ? 'Select an event name first' : undefined}
                                    options={[
                                        {
                                            label: 'on the date of the last event',
                                            value: 'last_event' as SubscriptionDropoffMode,
                                        },
                                        {
                                            label: 'after the dropoff period',
                                            value: 'after_dropoff_period' as SubscriptionDropoffMode,
                                        },
                                    ]}
                                />
                            </div>
                        </div>
                    </div>
                </div>
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex justify-end gap-2">
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSave} disabledReason={saveEventsDisabledReason}>
                        {originalEvent ? 'Update Event' : 'Add Event'}
                    </LemonButton>
                </div>
            </LemonModal.Footer>
        </LemonModal>
    )
}
