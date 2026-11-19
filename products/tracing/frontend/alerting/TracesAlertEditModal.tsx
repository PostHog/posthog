import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconBell, IconGraph, IconPulse, IconTarget } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { AlertEditor, AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'
import { AlertSummaryParts } from 'products/alerts/frontend/components/alertSummary'
import { SnoozeButton } from 'products/alerts/frontend/components/SnoozeButton'
import { EditAlertTab, EditAlertTabs } from 'products/alerts/frontend/views/EditAlertModal/EditAlertTabs'
import { platformAlertDestinationsLogic } from 'products/alerts_platform/frontend/destinations/platformAlertDestinationsLogic'
import { PlatformAlertNotifications } from 'products/alerts_platform/frontend/destinations/PlatformAlertNotifications'
import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'
import { PlatformAlertStateIndicator } from 'products/alerts_platform/frontend/PlatformAlertStateIndicator'
import { PlatformAlertStateTimeline } from 'products/alerts_platform/frontend/PlatformAlertStateTimeline'

import { confirmDeleteTracesAlert } from './confirmDeleteTracesAlert'
import { TracesAlertEventHistory } from './TracesAlertEventHistory'
import { TracesAlertFilterFields } from './TracesAlertFilterFields'
import { tracesAlertFormLogic } from './tracesAlertFormLogic'
import { tracesAlertsLogic } from './tracesAlertsLogic'
import { TracesAlertTriggerFields } from './TracesAlertTriggerFields'
import {
    describeTracesCondition,
    describeTracesScope,
    indicatorState,
    errorText,
    toWritePayload,
} from './tracesAlertUtils'

interface TracesAlertEditModalProps {
    alert: PlatformAlertConfigurationApi | null
    onClose: () => void
}

export function TracesAlertEditModal({ alert, onClose }: TracesAlertEditModalProps): JSX.Element {
    return (
        <LemonModal isOpen={alert !== null} onClose={onClose} title="" simple width={900}>
            {alert ? <TracesAlertEditModalContent alert={alert} onClose={onClose} /> : null}
        </LemonModal>
    )
}

function TracesAlertEditModalContent({
    alert,
    onClose,
}: {
    alert: PlatformAlertConfigurationApi
    onClose: () => void
}): JSX.Element {
    const formLogicProps = { alert, onSubmitSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, alertFormErrors, alertForm } = useValues(
        tracesAlertFormLogic(formLogicProps)
    )
    const { touchAlertFormField } = useActions(tracesAlertFormLogic(formLogicProps))
    const { destinations } = useValues(platformAlertDestinationsLogic({ alertId: alert.id, sourceKind: 'traces' }))
    const { snoozingAlertIds } = useValues(tracesAlertsLogic)
    const { deleteAlert, snoozeAlertUntil, toggleAlertEnabled, unsnoozeAlert } = useActions(tracesAlertsLogic)
    const payload = toWritePayload(alertForm, alert)

    const summary: AlertSummaryParts = {
        fires: describeTracesCondition(payload.source_config.condition),
        cadence: '',
        notifies: destinations.length
            ? `${destinations.length} ${destinations.length === 1 ? 'destination' : 'destinations'}`
            : '',
        filters: describeTracesScope(payload.source_config),
    }

    const tabs: EditAlertTab[] = [
        {
            key: 'monitor',
            summarySection: 'monitor',
            label: (
                <>
                    <IconPulse className="size-4" />
                    Monitor
                </>
            ),
            content: (
                <div className="space-y-3 pt-3">
                    <AlertEditorFormDetails nameError={errorText(alertFormErrors.name)} />
                    <div className="max-w-2xl space-y-6">
                        <TracesAlertFilterFields />
                    </div>
                </div>
            ),
        },
        {
            key: 'trigger',
            summarySection: 'monitor',
            label: (
                <>
                    <IconTarget className="size-4" />
                    Trigger
                </>
            ),
            content: (
                <div className="max-w-2xl space-y-6 pt-3">
                    <TracesAlertTriggerFields thresholdError={errorText(alertFormErrors.threshold)} />
                </div>
            ),
        },
        {
            key: 'notify',
            summarySection: 'notify',
            label: (
                <>
                    <IconBell className="size-4" />
                    Notify
                </>
            ),
            content: (
                <div className="pt-3">
                    <PlatformAlertNotifications alertId={alert.id} sourceKind="traces" />
                </div>
            ),
        },
        {
            key: 'history',
            label: (
                <>
                    <IconGraph className="size-4" />
                    History
                </>
            ),
            content: (
                <div className="pt-3">
                    <TracesAlertEventHistory alert={alert} />
                </div>
            ),
        },
    ]

    const leadingActions = (
        <div className="flex flex-wrap items-center gap-2">
            <LemonButton
                type="secondary"
                status="danger"
                onClick={() =>
                    confirmDeleteTracesAlert(alert, () => {
                        deleteAlert(alert)
                        onClose()
                    })
                }
                data-attr="traces-alert-edit-delete"
            >
                Delete alert
            </LemonButton>
            {alert.enabled ? (
                <SnoozeButton
                    onChange={(snoozeUntil) => snoozeAlertUntil(alert.id, snoozeUntil)}
                    onClear={alert.snooze_until ? () => unsnoozeAlert(alert.id) : undefined}
                    value={alert.snooze_until ?? undefined}
                    disabledReason={snoozingAlertIds.has(alert.id) ? 'Updating snooze' : undefined}
                />
            ) : null}
        </div>
    )

    return (
        <BindLogic logic={tracesAlertFormLogic} props={formLogicProps}>
            <Form
                logic={tracesAlertFormLogic}
                props={formLogicProps}
                formKey="alertForm"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <AlertEditor
                    title="Edit alert"
                    className="min-h-0 flex-1 overflow-hidden"
                    contentClassName="min-h-0 flex-1 overflow-y-auto"
                    onBack={onClose}
                    isEditing
                    isSubmitting={isAlertFormSubmitting}
                    hasChanges={alertFormChanged}
                    onSubmitAttempted={() => touchAlertFormField('name')}
                    leadingActions={leadingActions}
                    trailingActions={
                        <LemonSwitch
                            checked={alert.enabled}
                            label="Enabled"
                            onChange={() => toggleAlertEnabled(alert)}
                        />
                    }
                >
                    <EditAlertTabs
                        summary={summary}
                        summaryHeader={
                            <div className="flex items-center justify-between gap-3">
                                <span className="font-medium">Current status</span>
                                <PlatformAlertStateIndicator
                                    state={indicatorState(alert)}
                                    enabled={alert.enabled}
                                    firstEnabledAt={alert.created_at}
                                    lastErrorMessage={alert.last_error_message}
                                    snoozeUntil={alert.snooze_until}
                                />
                            </div>
                        }
                        statusNode={
                            <PlatformAlertStateTimeline
                                timeline={alert.state_timeline}
                                className="h-8 w-full"
                                showAxis
                            />
                        }
                        tabs={tabs}
                        showCadence={false}
                    />
                </AlertEditor>
            </Form>
        </BindLogic>
    )
}
