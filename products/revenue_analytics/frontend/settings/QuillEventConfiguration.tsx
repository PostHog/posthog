import { IconGear, IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { CURRENCY_SYMBOL_TO_EMOJI_MAP, getCurrencySymbol } from 'lib/utils/currency'

import { RevenueAnalyticsEventItem } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

function LabeledCode({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <Text size="xs" render={<span className="m-0" />}>
            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                {label}:
            </Text>{' '}
            <code>{value}</code>
        </Text>
    )
}

function MutedNote({ children }: { children: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span className="m-0" />}>
            {children}
        </Text>
    )
}

export interface QuillEventConfigurationProps {
    hideDescription?: boolean
    events: RevenueAnalyticsEventItem[]
    onAddEvent: () => void
    onEditEvent: (event: RevenueAnalyticsEventItem) => void
    onRemoveEvent: (event: RevenueAnalyticsEventItem) => void
}

export function QuillEventConfiguration({
    hideDescription = false,
    events,
    onAddEvent,
    onEditEvent,
    onRemoveEvent,
}: QuillEventConfigurationProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
                {!hideDescription && (
                    <Text size="xs" render={<p className="m-0 max-w-160" />}>
                        PostHog can display revenue data in our Revenue Analytics product from any event. You can
                        configure as many events as you want, and specify the revenue property and currency for each
                        event individually.
                    </Text>
                )}
                <AccessControlAction
                    resourceType={AccessControlResourceType.RevenueAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button variant="primary" onClick={onAddEvent}>
                        <IconPlus />
                        Add Revenue Event
                    </Button>
                </AccessControlAction>
            </div>
            <Table fullWidth className="rounded-md border border-border">
                <TableHeader>
                    <TableRow>
                        <TableHead>Event Name</TableHead>
                        <TableHead>Revenue Property</TableHead>
                        <TableHead>Currency</TableHead>
                        <TableHead expand>Additional Properties</TableHead>
                        <TableHead />
                    </TableRow>
                </TableHeader>
                {events.length === 0 ? (
                    <TableEmpty>
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>No event sources configured yet</EmptyTitle>
                            </EmptyHeader>
                        </Empty>
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {events.map((item) => (
                            <TableRow key={item.eventName}>
                                <TableCell>
                                    <code>{item.eventName}</code>
                                </TableCell>
                                <TableCell>
                                    {item.revenueProperty ? (
                                        <code>{item.revenueProperty}</code>
                                    ) : (
                                        <MutedNote>Not set</MutedNote>
                                    )}
                                </TableCell>
                                <TableCell>
                                    <div className="flex flex-col gap-1">
                                        {item.revenueCurrencyProperty.property && (
                                            <LabeledCode
                                                label="Property"
                                                value={item.revenueCurrencyProperty.property}
                                            />
                                        )}
                                        {item.revenueCurrencyProperty.static && (
                                            <Text size="xs" render={<span className="m-0" />}>
                                                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                                    Static:
                                                </Text>{' '}
                                                <span className="font-medium">
                                                    {CURRENCY_SYMBOL_TO_EMOJI_MAP[item.revenueCurrencyProperty.static]}
                                                    &nbsp;{item.revenueCurrencyProperty.static}&nbsp;(
                                                    {getCurrencySymbol(item.revenueCurrencyProperty.static).symbol})
                                                </span>
                                            </Text>
                                        )}
                                        {item.currencyAwareDecimal && <MutedNote>In cents</MutedNote>}
                                        {!item.revenueCurrencyProperty.property &&
                                            !item.revenueCurrencyProperty.static && (
                                                <MutedNote>Not configured</MutedNote>
                                            )}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <div className="flex flex-col gap-1">
                                        {item.productProperty && (
                                            <LabeledCode label="Product" value={item.productProperty} />
                                        )}
                                        {item.couponProperty && (
                                            <LabeledCode label="Coupon" value={item.couponProperty} />
                                        )}
                                        {item.subscriptionProperty && (
                                            <>
                                                <LabeledCode label="Subscription" value={item.subscriptionProperty} />
                                                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                                    Drop subscription after {item.subscriptionDropoffDays} days
                                                </Text>
                                                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                                    Subscription ends on the day{' '}
                                                    {item.subscriptionDropoffMode === 'last_event'
                                                        ? 'of the last event'
                                                        : 'the dropoff period ends'}
                                                </Text>
                                            </>
                                        )}
                                        {!item.productProperty &&
                                            !item.couponProperty &&
                                            !item.subscriptionProperty && <MutedNote>None configured</MutedNote>}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <div className="flex items-center gap-1">
                                        <AccessControlAction
                                            resourceType={AccessControlResourceType.RevenueAnalytics}
                                            minAccessLevel={AccessControlLevel.Editor}
                                        >
                                            <Button
                                                variant="outline"
                                                size="icon"
                                                aria-label="Edit event configuration"
                                                tooltip="Edit event configuration"
                                                onClick={() => onEditEvent(item)}
                                            >
                                                <IconGear />
                                            </Button>
                                        </AccessControlAction>
                                        <AccessControlAction
                                            resourceType={AccessControlResourceType.RevenueAnalytics}
                                            minAccessLevel={AccessControlLevel.Editor}
                                        >
                                            <Button
                                                variant="destructive-outline"
                                                size="icon"
                                                aria-label="Remove event"
                                                tooltip="Remove event"
                                                onClick={() => onRemoveEvent(item)}
                                            >
                                                <IconTrash />
                                            </Button>
                                        </AccessControlAction>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                )}
            </Table>
        </div>
    )
}
