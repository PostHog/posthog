import { useActions, useValues } from 'kea'

import { IconInfo, IconTrash } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { CurrencyDropdown } from 'lib/components/BaseCurrency/CurrencyDropdown'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { RevenueAnalyticsEventItem, SubscriptionDropoffMode } from '~/queries/schema/schema-general'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

export function EventConfiguration({ buttonRef }: { buttonRef?: React.RefObject<HTMLButtonElement> }): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const { events, saveEventsDisabledReason, changesMadeToEvents } = useValues(revenueAnalyticsSettingsLogic)
    const {
        addEvent,
        deleteEvent,
        updateEventCouponProperty,
        updateEventCurrencyAwareDecimalProperty,
        updateEventCurrencyProperty,
        updateEventProductProperty,
        updateEventRevenueProperty,
        updateEventSubscriptionProperty,
        updateEventSubscriptionDropoffDays,
        updateEventSubscriptionDropoffMode,
        save,
    } = useActions(revenueAnalyticsSettingsLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    return (
        <SceneSection
            hideTitleAndDescription={!newSceneLayout}
            className={cn(!newSceneLayout && 'gap-y-0')}
            title="Event Configuration"
            description="PostHog can display revenue data in our Revenue Analytics product from any event. You can configure as many events as you want, and specify the revenue property and currency for each event individually."
        >
            {!newSceneLayout && (
                <>
                    <h3 className="mb-2">Event Configuration</h3>
                    <p className="mb-4">
                        PostHog can display revenue data in our Revenue Analytics product from any event. You can
                        configure as many events as you want, and specify the revenue property and currency for each
                        event individually.
                        <br />
                        <br />
                        You can also configure several properties for each event, such as the product property (to break
                        down revenue by product), the coupon property (to break down revenue by coupon), and the
                        subscription property (to properly calculate ARPU and LTV).
                    </p>
                </>
            )}
            <div className="flex flex-col mb-1 items-end w-full">
                <div className="flex flex-row w-full gap-1 justify-end my-2">
                    <TaxonomicPopover
                        type="primary"
                        groupType={TaxonomicFilterGroupType.CustomEvents}
                        onChange={(eventName) => addEvent(eventName as string, baseCurrency)}
                        value={undefined}
                        placeholder="Create revenue event"
                        placeholderClass=""
                        excludedProperties={{
                            [TaxonomicFilterGroupType.CustomEvents]: [null, ...events.map((item) => item.eventName)],
                        }}
                        id="data-management-revenue-settings-add-event"
                        ref={buttonRef}
                    />

                    {changesMadeToEvents && (
                        <LemonButton type="primary" onClick={save} disabledReason={saveEventsDisabledReason}>
                            Save
                        </LemonButton>
                    )}
                </div>
                {changesMadeToEvents && (
                    <span className="text-xs text-error normal-case font-normal">
                        Remember to save your changes to take effect
                    </span>
                )}
            </div>
            <LemonTable<RevenueAnalyticsEventItem>
                dataSource={events}
                rowKey={(item) => item.eventName}
                emptyState="No event sources configured yet"
                columns={[
                    { key: 'eventName', title: 'Event name˟', dataIndex: 'eventName' },
                    {
                        key: 'revenueProperty',
                        dataIndex: 'revenueProperty',
                        title: 'Revenue property˟',
                        tooltip:
                            'The property that tracks the amount of revenue generated by the event. This could be a different property for each event.',

                        render: (_, item: RevenueAnalyticsEventItem) => {
                            return (
                                <div className="flex flex-row w-full my-1">
                                    <TaxonomicPopover
                                        showNumericalPropsOnly
                                        size="small"
                                        groupType={TaxonomicFilterGroupType.EventProperties}
                                        onChange={(newPropertyName) =>
                                            updateEventRevenueProperty(item.eventName, newPropertyName)
                                        }
                                        value={item.revenueProperty}
                                        placeholder="Choose property"
                                        disabledReason={
                                            item.eventName === '$pageview' || item.eventName === '$autocapture'
                                                ? 'Built-in events must use revenue'
                                                : undefined
                                        }
                                    />
                                </div>
                            )
                        },
                    },
                    {
                        key: 'revenueCurrencyProperty',
                        dataIndex: 'revenueCurrencyProperty',
                        title: 'Currency property˟',
                        tooltip:
                            'The currency of the revenue event. You can choose between a property on your event OR a fixed currency for all events.',
                        render: (_, item: RevenueAnalyticsEventItem) => {
                            return (
                                <div className="flex flex-col w-full gap-3 my-1 whitespace-nowrap">
                                    <div className="flex flex-row gap-1">
                                        <span className="font-bold">Dynamic property: </span>
                                        <TaxonomicPopover
                                            size="small"
                                            groupType={TaxonomicFilterGroupType.EventProperties}
                                            onChange={(newPropertyName) =>
                                                updateEventCurrencyProperty(item.eventName, {
                                                    property: newPropertyName,
                                                })
                                            }
                                            value={item.revenueCurrencyProperty.property ?? null}
                                            placeholder="Choose property"
                                        />
                                    </div>
                                    <div className="flex flex-row gap-1">
                                        or <span className="font-bold">Static currency: </span>
                                        <CurrencyDropdown
                                            size="small"
                                            onChange={(currency) =>
                                                updateEventCurrencyProperty(item.eventName, {
                                                    static: currency,
                                                })
                                            }
                                            value={item.revenueCurrencyProperty.static ?? null}
                                        />
                                    </div>
                                    <div className="flex flex-row gap-1">
                                        <Tooltip title="Whether you are sending revenue in the smallest unit of currency (e.g. cents for USD, yen for JPY) or on the normal denomination (e.g. dollars for USD, yen for JPY). If enabled, we divide the property value by the smallest unit of currency (e.g. 100 for USD, 1 for JPY).">
                                            <span className="font-bold">In cents? </span>
                                            <IconInfo />
                                        </Tooltip>
                                        <LemonSwitch
                                            checked={item.currencyAwareDecimal}
                                            onChange={(checked) =>
                                                updateEventCurrencyAwareDecimalProperty(item.eventName, checked)
                                            }
                                        />
                                    </div>
                                </div>
                            )
                        },
                    },
                    {
                        key: 'productProperty',
                        dataIndex: 'productProperty',
                        title: 'Product property',
                        tooltip:
                            'The property that tracks which product generated this revenue event. Useful if you wanna break revenue down by individual products.',
                        render: (_, item: RevenueAnalyticsEventItem) => {
                            return (
                                <div className="flex flex-row w-full my-1">
                                    <TaxonomicPopover
                                        size="small"
                                        className="my-1"
                                        groupType={TaxonomicFilterGroupType.EventProperties}
                                        onChange={(newPropertyName) =>
                                            updateEventProductProperty(item.eventName, newPropertyName)
                                        }
                                        value={item.productProperty}
                                        placeholder="Choose property"
                                    />
                                </div>
                            )
                        },
                    },
                    {
                        key: 'couponProperty',
                        dataIndex: 'couponProperty',
                        title: 'Coupon property',
                        tooltip:
                            'The property that tracks which coupon generated this revenue event. Useful if you wanna break revenue down by individual coupons.',
                        render: (_, item: RevenueAnalyticsEventItem) => {
                            return (
                                <div className="flex flex-row w-full my-1">
                                    <TaxonomicPopover
                                        size="small"
                                        className="my-1"
                                        groupType={TaxonomicFilterGroupType.EventProperties}
                                        onChange={(newPropertyName) =>
                                            updateEventCouponProperty(item.eventName, newPropertyName)
                                        }
                                        value={item.couponProperty}
                                        placeholder="Choose property"
                                    />
                                </div>
                            )
                        },
                    },
                    {
                        key: 'subscriptionProperty',
                        dataIndex: 'subscriptionProperty',
                        title: 'Subscription property',
                        tooltip:
                            'The property that tracks which subscription generated this revenue event. Useful if you wanna be able to track ARPU and LTV.',
                        render: (_, item: RevenueAnalyticsEventItem) => {
                            return (
                                <div className="flex flex-row w-full my-1">
                                    <TaxonomicPopover
                                        size="small"
                                        className="my-1"
                                        groupType={TaxonomicFilterGroupType.EventProperties}
                                        onChange={(newPropertyName) =>
                                            updateEventSubscriptionProperty(item.eventName, newPropertyName)
                                        }
                                        value={item.subscriptionProperty}
                                        placeholder="Choose property"
                                    />
                                </div>
                            )
                        },
                    },

                    {
                        key: 'subscriptionDropoffDays',
                        dataIndex: 'subscriptionDropoffDays',
                        title: 'Subscription dropoff in days',
                        tooltip:
                            "The number of days we still consider a subscription to be active after the last event. This is useful to avoid the current month's data to look as if most of the subscriptions have churned since we might not have an event for the current month.",
                        fullWidth: true,
                        render: (_, item: RevenueAnalyticsEventItem) => {
                            return (
                                <div className="flex flex-col w-full whitespace-nowrap my-1 gap-3">
                                    <div className="flex flex-row items-center w-full gap-2">
                                        <LemonInput
                                            type="number"
                                            size="small"
                                            className="min-w-16"
                                            min={1}
                                            max={365}
                                            value={item.subscriptionProperty ? item.subscriptionDropoffDays : undefined}
                                            onChange={(value) => {
                                                if (Number.isNaN(value) || !value || value < 1 || value > 365) {
                                                    value = 45
                                                }

                                                updateEventSubscriptionDropoffDays(item.eventName, Number(value))
                                            }}
                                            disabledReason={
                                                !item.subscriptionProperty
                                                    ? 'Only available when subscription property is set'
                                                    : undefined
                                            }
                                        />
                                        <span>days</span>
                                    </div>
                                    <div className="flex flex-row items-center w-full gap-2">
                                        <span className="text-nowrap">Subscription ends</span>
                                        <LemonSelect<SubscriptionDropoffMode>
                                            size="small"
                                            options={[
                                                {
                                                    label: 'on the date of the last event',
                                                    value: 'last_event' as SubscriptionDropoffMode,
                                                    tooltip: `The subscription will be considered active for ${item.subscriptionDropoffDays} and then will be considered to have ended on the day of the last event (i.e. it will backfill the subscription to the last event altering history). This is useful if you want to keep accurate ARPU calculations, but it might change metrics from past months (users will churn in the past).`,
                                                },
                                                {
                                                    label: 'after the dropoff period',
                                                    value: 'after_dropoff_period' as SubscriptionDropoffMode,
                                                    tooltip: `The subscription will be considered to have ended on the day of the last event plus the dropoff period (i.e. ${item.subscriptionDropoffDays} days after the last event). This is useful if you want to make sure past months calculations won't change, but it might decrease ARPU since users will be considered active for longer but without paying.`,
                                                },
                                            ]}
                                            value={item.subscriptionDropoffMode}
                                            onChange={(value) =>
                                                updateEventSubscriptionDropoffMode(item.eventName, value)
                                            }
                                            disabledReason={
                                                !item.subscriptionProperty
                                                    ? 'Only available when subscription property is set'
                                                    : undefined
                                            }
                                        />
                                    </div>
                                </div>
                            )
                        },
                    },
                    {
                        key: 'actions',
                        render: (_, item) => (
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => deleteEvent(item.eventName)}
                                icon={<IconTrash />}
                            >
                                Remove
                            </LemonButton>
                        ),
                    },
                ]}
            />
        </SceneSection>
    )
}
