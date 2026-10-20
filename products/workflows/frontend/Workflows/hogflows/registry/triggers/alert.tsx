import { useActions, useValues } from 'kea'

import { IconBell } from '@posthog/icons'
import { LemonBanner, LemonInputSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import {
    ALERT_TRANSITION_EVENT,
    ALERT_TRANSITION_OPTIONS,
    AlertTriggerFilters,
    decodeAlertFilters,
    encodeAlertFilters,
    InternalEventAlertTriggerConfig,
    isAlertTransitionTriggerConfig,
} from './alertTriggerFilters'
import { alertTriggerOptionsLogic } from './alertTriggerOptionsLogic'

function StepTriggerConfigurationAlert({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { alerts, alertsLoading } = useValues(alertTriggerOptionsLogic)
    const { loadAlerts } = useActions(alertTriggerOptionsLogic)

    const config = node.data.config as InternalEventAlertTriggerConfig
    const filters = decodeAlertFilters(config.filters?.properties)
    const validationResult = actionValidationErrorsById[node.data.id]

    const update = (changes: Partial<AlertTriggerFilters>): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'internal-event',
            filters: {
                source: 'internal-events',
                events: [{ id: ALERT_TRANSITION_EVENT, type: 'events' }],
                properties: encodeAlertFilters({ ...filters, ...changes }),
            },
        })
    }

    if (alerts === null && alertsLoading) {
        return <p className="mb-0 text-sm text-muted-alt">Loading alerts…</p>
    }
    if (alerts === null) {
        return (
            <LemonBanner type="error" className="w-full" action={{ children: 'Try again', onClick: loadAlerts }}>
                Couldn't load this project's alerts.
            </LemonBanner>
        )
    }
    if (alerts.length === 0) {
        return (
            <LemonBanner type="info" className="w-full">
                This project has no alerts a workflow can use yet. Create a logs alert first.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <LemonField.Pure label="Alerts" error={validationResult?.errors?.alertIds}>
                <LemonInputSelect
                    mode="multiple"
                    value={filters.alertIds}
                    options={alerts.map((alert) => ({ key: alert.id, label: alert.name }))}
                    placeholder="Pick one or more alerts"
                    onChange={(alertIds) => update({ alertIds })}
                    data-attr="alert-trigger-alerts"
                />
            </LemonField.Pure>
            <LemonField.Pure label="When the alert" info="Leave empty to run on every change.">
                <LemonInputSelect
                    mode="multiple"
                    value={filters.transitions}
                    options={ALERT_TRANSITION_OPTIONS.map(({ value, label }) => ({ key: value, label }))}
                    placeholder="Any change"
                    onChange={(transitions) => update({ transitions })}
                    data-attr="alert-trigger-transitions"
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    // The tile's own identity, not the stored config type: `internal-event` carries every internal
    // event, so naming the tile after it would make the alert tile claim all of them.
    value: 'alert-transition',
    label: 'Alert',
    icon: <IconBell />,
    description: 'Trigger when an alert fires, resolves, or fails',
    group: 'Alerts',
    featureFlag: 'alert-platform-transition-event',
    matchConfig: (config) => isAlertTransitionTriggerConfig(config),
    buildConfig: () => ({
        type: 'internal-event',
        filters: {
            source: 'internal-events',
            events: [{ id: ALERT_TRANSITION_EVENT, type: 'events' }],
            properties: [],
        },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (!isAlertTransitionTriggerConfig(config)) {
            return null
        }
        if (!decodeAlertFilters(config.filters?.properties).alertIds.length) {
            return { valid: false, errors: { alertIds: 'Pick at least one alert' } }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationAlert,
})
