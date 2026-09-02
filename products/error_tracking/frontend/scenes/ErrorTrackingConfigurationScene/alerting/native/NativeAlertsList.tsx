import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonCard, LemonSwitch, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { AnyPropertyFilter } from '~/types'

import { ErrorTrackingAlertApi, ErrorTrackingAlertDestinationApi } from '../../../../generated/api.schemas'
import { errorTrackingEditAccessDisabledReason } from '../../../../utils'
import { THROTTLE_OPTIONS, TRIGGER_OPTIONS, nativeAlertEditorLogic } from './nativeAlertEditorLogic'
import { nativeAlertsLogic } from './nativeAlertsLogic'

function throttleLabel(seconds: number): string {
    return THROTTLE_OPTIONS.find((option) => option.value === seconds)?.label ?? `Once every ${seconds}s`
}

function propertyLabel(property: AnyPropertyFilter): string {
    const key = 'key' in property ? String(property.key) : ''
    const operator = 'operator' in property && property.operator ? property.operator.replace(/_/g, ' ') : 'is'
    const value = 'value' in property ? property.value : undefined
    const rendered = Array.isArray(value)
        ? value.join(', ')
        : value === undefined || value === null
          ? ''
          : String(value)
    return `${key} ${operator} ${rendered}`.trim()
}

function DeliveryHealth({ destinations }: { destinations: ErrorTrackingAlertDestinationApi[] }): JSX.Element | null {
    const failing = destinations.find((destination) => destination.consecutive_failures > 0)
    if (failing) {
        return (
            <LemonTag type="danger" size="small">
                Failing: {failing.last_error || 'delivery error'}
            </LemonTag>
        )
    }
    const lastDelivered = destinations
        .map((destination) => destination.last_delivered_at)
        .filter((value): value is string => !!value)
        .sort()
        .at(-1)
    if (lastDelivered) {
        return (
            <LemonTag type="success" size="small">
                Delivered <TZLabel time={lastDelivered} />
            </LemonTag>
        )
    }
    return null
}

function AlertCard({ alert }: { alert: ErrorTrackingAlertApi }): JSX.Element {
    const { alertsLoading } = useValues(nativeAlertsLogic)
    const { setAlertEnabled } = useActions(nativeAlertsLogic)
    const { openEditor } = useActions(nativeAlertEditorLogic)
    const editDisabledReason = errorTrackingEditAccessDisabledReason() ?? undefined
    const properties = (alert.filters.properties ?? []) as AnyPropertyFilter[]

    return (
        <LemonCard hoverEffect={false} className={alert.enabled ? 'flex flex-col p-0' : 'flex flex-col p-0 opacity-70'}>
            <div className="flex items-center justify-between gap-2 px-3 py-2">
                <div className="flex items-center gap-2 min-w-0">
                    <LemonSwitch
                        checked={alert.enabled}
                        onChange={(enabled) => setAlertEnabled({ alert, enabled })}
                        disabledReason={editDisabledReason ?? (alertsLoading ? 'Updating' : undefined)}
                        size="small"
                    />
                    <span className="font-semibold truncate">{alert.name}</span>
                    <DeliveryHealth destinations={alert.destinations} />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <LemonTag size="small">{throttleLabel(alert.throttle_seconds)}</LemonTag>
                    <LemonButton
                        size="small"
                        type="tertiary"
                        onClick={() => openEditor(alert)}
                        disabledReason={editDisabledReason}
                    >
                        Edit
                    </LemonButton>
                </div>
            </div>
            <div className="border-t grid gap-3 px-3 py-2.5 @[640px]:grid-cols-3">
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold uppercase text-secondary">Opens a thread when</span>
                    <div className="flex flex-wrap gap-1">
                        {alert.triggers.map((trigger) => (
                            <LemonTag key={trigger} type="highlight" size="small">
                                {TRIGGER_OPTIONS.find((option) => option.value === trigger)?.label ?? trigger}
                            </LemonTag>
                        ))}
                    </div>
                </div>
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold uppercase text-secondary">Only if</span>
                    <div className="flex flex-wrap gap-1">
                        {properties.length === 0 ? (
                            <span className="text-secondary text-sm">Every matching issue</span>
                        ) : (
                            properties.map((property, index) => (
                                <LemonTag key={index} size="small">
                                    {propertyLabel(property)}
                                </LemonTag>
                            ))
                        )}
                    </div>
                </div>
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold uppercase text-secondary">Posts to</span>
                    <div className="flex flex-wrap gap-1">
                        {alert.destinations.map((destination) => (
                            <LemonTag
                                key={destination.id}
                                size="small"
                                type={destination.consecutive_failures > 0 ? 'danger' : 'default'}
                            >
                                {destination.config.channel_name || destination.config.channel}
                            </LemonTag>
                        ))}
                    </div>
                </div>
            </div>
        </LemonCard>
    )
}

export function NativeAlertsList(): JSX.Element {
    const { alerts, alertsLoading } = useValues(nativeAlertsLogic)
    const { loadAlerts } = useActions(nativeAlertsLogic)
    const { openEditor } = useActions(nativeAlertEditorLogic)

    useEffect(() => {
        loadAlerts()
    }, [loadAlerts])

    return (
        <div className="flex flex-col gap-2 @container">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{alerts.length}</span>
                    <span className="text-secondary">{alerts.length === 1 ? 'alert' : 'alerts'}</span>
                    {alertsLoading && alerts.length === 0 && <Spinner />}
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => openEditor()}
                    disabledReason={errorTrackingEditAccessDisabledReason() ?? undefined}
                    data-attr="error-tracking-new-alert"
                >
                    New alert
                </LemonButton>
            </div>
            {alerts.length === 0 && !alertsLoading ? (
                <LemonCard hoverEffect={false} className="text-secondary text-sm">
                    No alerts yet. An alert opens one Slack thread per issue and keeps it updated as the issue changes.
                </LemonCard>
            ) : (
                alerts.map((alert) => <AlertCard key={alert.id} alert={alert} />)
            )}
        </div>
    )
}
