import { useId } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    Label,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Switch,
    Text,
} from '@posthog/quill'

import { QuillCurrencyDropdown } from 'lib/components/BaseCurrency/QuillCurrencyDropdown'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { CurrencyCode, RevenueAnalyticsEventItem, SubscriptionDropoffMode } from '~/queries/schema/schema-general'

const DROPOFF_MODE_OPTIONS: { label: string; value: SubscriptionDropoffMode }[] = [
    { label: 'on the date of the last event', value: 'last_event' },
    { label: 'after the dropoff period', value: 'after_dropoff_period' },
]

export interface QuillEventConfigurationModalProps {
    originalEvent: RevenueAnalyticsEventItem | null
    currentEvent: RevenueAnalyticsEventItem | null
    accessDeniedReason: string | null | undefined
    saveDisabledReason: string | null | undefined
    eventFieldDisabledReason: string | undefined
    revenuePropertyDisabledReason: string | undefined
    onSelectEventName: (eventName: string) => void
    onRevenuePropertyChange: (propertyName: string) => void
    onCurrencyPropertyChange: (propertyName: string) => void
    onStaticCurrencyChange: (currency: CurrencyCode) => void
    onCurrencyAwareDecimalChange: (checked: boolean) => void
    onProductPropertyChange: (propertyName: string) => void
    onCouponPropertyChange: (propertyName: string) => void
    onSubscriptionPropertyChange: (propertyName: string) => void
    onDropoffDaysChange: (value: number | null) => void
    onDropoffModeChange: (value: SubscriptionDropoffMode | null) => void
    onSave: () => void
    onClose: () => void
}

export function QuillEventConfigurationModal({
    originalEvent,
    currentEvent,
    accessDeniedReason,
    saveDisabledReason,
    eventFieldDisabledReason,
    revenuePropertyDisabledReason,
    onSelectEventName,
    onRevenuePropertyChange,
    onCurrencyPropertyChange,
    onStaticCurrencyChange,
    onCurrencyAwareDecimalChange,
    onProductPropertyChange,
    onCouponPropertyChange,
    onSubscriptionPropertyChange,
    onDropoffDaysChange,
    onDropoffModeChange,
    onSave,
    onClose,
}: QuillEventConfigurationModalProps): JSX.Element {
    const id = useId()
    const isReadOnly = !!accessDeniedReason

    return (
        <Dialog
            open
            onOpenChange={(open) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <DialogContent className="sm:max-w-200">
                <DialogHeader>
                    <DialogTitle>
                        {originalEvent ? `Edit Event: ${originalEvent?.eventName}` : 'Add Revenue Event'}
                    </DialogTitle>
                </DialogHeader>

                <DialogBody>
                    <div className="flex flex-col gap-4">
                        {isReadOnly && (
                            <Item tone="warning" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        <strong>Read only:</strong> {accessDeniedReason} Ask a workspace admin to grant
                                        you Editor access to Revenue analytics to add or change events.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}

                        {!originalEvent && !isReadOnly && (
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        <strong>How it works:</strong> PostHog will track this event and use these
                                        properties for revenue calculations. You can always modify these settings later.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}

                        <Field>
                            <Label>
                                Event Name <span className="text-destructive-foreground">*</span>
                            </Label>
                            {currentEvent ? (
                                <>
                                    <code className="w-fit font-mono">{currentEvent.eventName}</code>
                                    <FieldDescription>
                                        Event name cannot be changed when editing. You can delete and add a new event
                                        instead.
                                    </FieldDescription>
                                </>
                            ) : (
                                <TaxonomicPopover
                                    type="primary"
                                    groupType={TaxonomicFilterGroupType.CustomEvents}
                                    onChange={onSelectEventName}
                                    value=""
                                    placeholder="Select or type an event name"
                                    selectingKeyOnly
                                />
                            )}
                        </Field>

                        <Separator />

                        <Field>
                            <Label>
                                Revenue Property <span className="text-destructive-foreground">*</span>
                            </Label>
                            <TaxonomicPopover
                                showNumericalPropsOnly
                                groupType={TaxonomicFilterGroupType.EventProperties}
                                onChange={onRevenuePropertyChange}
                                value={currentEvent?.revenueProperty || undefined}
                                placeholder="Select the property that contains revenue amount"
                                selectingKeyOnly
                                disabledReason={revenuePropertyDisabledReason}
                            />
                            <FieldDescription>
                                Choose the property that tracks the amount of revenue generated by this event.
                            </FieldDescription>
                            {currentEvent?.eventName && !currentEvent?.revenueProperty && (
                                <Item tone="info" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            Only <strong>numeric</strong> properties are listed. If your revenue
                                            property is missing, open it in{' '}
                                            <Button
                                                variant="link"
                                                size="inline"
                                                nativeButton={false}
                                                render={
                                                    <LinkPrimitive to={urls.propertyDefinitions()} target="_blank" />
                                                }
                                            >
                                                Property Definitions
                                            </Button>{' '}
                                            and set its type to <code>Numeric</code>, then reopen this modal.
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                            )}
                        </Field>

                        <Separator />

                        <div className="flex flex-col gap-2">
                            <Heading size="sm" render={<h3 className="m-0" />}>
                                Currency Configuration
                            </Heading>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Choose how to handle currency for this event. You can either use a dynamic property that
                                contains the 3-letter currency code for each event, or set a static currency that
                                applies to all events of this type.
                            </Text>
                        </div>

                        <div className="flex flex-wrap items-end gap-4">
                            <Field className="w-auto">
                                <Label>Dynamic Currency Property</Label>
                                <TaxonomicPopover
                                    groupType={TaxonomicFilterGroupType.EventProperties}
                                    onChange={onCurrencyPropertyChange}
                                    value={currentEvent?.revenueCurrencyProperty.property || undefined}
                                    placeholder="Select property for dynamic currency"
                                    disabledReason={eventFieldDisabledReason}
                                />
                            </Field>
                            <Text size="xs" variant="muted" render={<span className="m-0 pb-2 font-bold" />}>
                                OR
                            </Text>
                            <Field className="w-auto">
                                <Label>Static Currency</Label>
                                <QuillCurrencyDropdown
                                    onChange={onStaticCurrencyChange}
                                    value={currentEvent?.revenueCurrencyProperty.static || null}
                                    disabledReason={eventFieldDisabledReason}
                                />
                            </Field>
                        </div>

                        <Field orientation="horizontal">
                            <Switch
                                id={`${id}-cents`}
                                checked={currentEvent?.currencyAwareDecimal || false}
                                onCheckedChange={onCurrencyAwareDecimalChange}
                                disabledReason={eventFieldDisabledReason}
                            />
                            <FieldContent>
                                <FieldLabel htmlFor={`${id}-cents`}>Values are in cents</FieldLabel>
                                <FieldDescription>
                                    Enable this if your revenue values are in the smallest unit of currency (e.g. cents
                                    for USD, yen for JPY). We will divide by the smallest unit (e.g. 100 for USD, 1 for
                                    JPY)
                                </FieldDescription>
                            </FieldContent>
                        </Field>

                        <Separator />

                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Advanced Properties (Optional)
                        </Heading>

                        <div className="flex flex-wrap gap-4">
                            <Field className="min-w-60 flex-1">
                                <Label>Product Property</Label>
                                <TaxonomicPopover
                                    groupType={TaxonomicFilterGroupType.EventProperties}
                                    onChange={onProductPropertyChange}
                                    value={currentEvent?.productProperty || undefined}
                                    placeholder="Select product property"
                                    disabledReason={eventFieldDisabledReason}
                                />
                                <FieldDescription>
                                    Track which product was responsible for generating this revenue event
                                </FieldDescription>
                            </Field>

                            <Field className="min-w-60 flex-1">
                                <Label>Coupon Property</Label>
                                <TaxonomicPopover
                                    groupType={TaxonomicFilterGroupType.EventProperties}
                                    onChange={onCouponPropertyChange}
                                    value={currentEvent?.couponProperty || undefined}
                                    placeholder="Select coupon property"
                                    disabledReason={eventFieldDisabledReason}
                                />
                                <FieldDescription>
                                    Track which coupon was applied to this revenue event
                                </FieldDescription>
                            </Field>
                        </div>

                        <Separator />

                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Subscription Tracking
                        </Heading>

                        <Field>
                            <Label>Subscription Property</Label>
                            <TaxonomicPopover
                                groupType={TaxonomicFilterGroupType.EventProperties}
                                onChange={onSubscriptionPropertyChange}
                                value={currentEvent?.subscriptionProperty || undefined}
                                placeholder="Select subscription property (optional)"
                                disabledReason={eventFieldDisabledReason}
                            />
                            <FieldDescription>
                                Track subscription information for ARPU and LTV calculations. Recommended for better
                                revenue insights.
                            </FieldDescription>
                        </Field>

                        <div className="flex flex-wrap gap-4">
                            <Field className="min-w-60 flex-1">
                                <FieldLabel htmlFor={`${id}-dropoff-days`}>Dropoff Days</FieldLabel>
                                <NumberFieldRoot
                                    min={1}
                                    max={365}
                                    value={currentEvent?.subscriptionDropoffDays || 45}
                                    onValueChange={onDropoffDaysChange}
                                    disabledReason={eventFieldDisabledReason}
                                >
                                    <NumberFieldGroup>
                                        <NumberFieldInput id={`${id}-dropoff-days`} />
                                    </NumberFieldGroup>
                                </NumberFieldRoot>
                                <FieldDescription>
                                    Days to consider subscription active after last event
                                </FieldDescription>
                            </Field>

                            <Field className="min-w-60 flex-1">
                                <FieldLabel htmlFor={`${id}-dropoff-mode`}>Dropoff Mode</FieldLabel>
                                <Select
                                    items={DROPOFF_MODE_OPTIONS}
                                    value={currentEvent?.subscriptionDropoffMode || 'last_event'}
                                    onValueChange={onDropoffModeChange}
                                >
                                    <SelectTrigger id={`${id}-dropoff-mode`} disabledReason={eventFieldDisabledReason}>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {DROPOFF_MODE_OPTIONS.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </Field>
                        </div>
                    </div>
                </DialogBody>

                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={onSave} disabledReason={saveDisabledReason}>
                        {originalEvent ? 'Update Event' : 'Add Event'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
