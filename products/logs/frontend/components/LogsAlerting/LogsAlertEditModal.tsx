import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconBell, IconGraph, IconList, IconPulse, IconTarget } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { AlertEditor, AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'
import { AlertSummaryParts } from 'products/alerts/frontend/components/alertSummary'
import { SnoozeButton } from 'products/alerts/frontend/components/SnoozeButton'
import { EditAlertTab, EditAlertTabs } from 'products/alerts/frontend/views/EditAlertModal/EditAlertTabs'
import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertEventHistoryContent } from './LogsAlertEventHistory'
import { LogsAlertFilters, LogsAlertTrigger } from './LogsAlertForm'
import { logsAlertFormLogic } from './logsAlertFormLogic'
import { logsAlertingLogic } from './logsAlertingLogic'
import { logsAlertNotificationLogic } from './logsAlertNotificationLogic'
import { LogsAlertNotifications } from './LogsAlertNotifications'
import { LogsAlertSimulation } from './LogsAlertSimulation'
import { LogsAlertStateIndicator } from './LogsAlertStateIndicator'
import { LogsAlertStateTimeline } from './LogsAlertStateTimeline'

interface LogsAlertEditModalProps {
    alert: LogsAlertConfigurationApi | null
    onClose: () => void
}

export function LogsAlertEditModal({ alert, onClose }: LogsAlertEditModalProps): JSX.Element {
    return (
        <LemonModal isOpen={alert !== null} onClose={onClose} title="" simple width={900}>
            {alert ? <LogsAlertEditModalContent alert={alert} onClose={onClose} /> : null}
        </LemonModal>
    )
}

function LogsAlertEditModalContent({
    alert,
    onClose,
}: {
    alert: LogsAlertConfigurationApi
    onClose: () => void
}): JSX.Element {
    const formLogicProps = { alert, onSubmitSuccess: onClose }
    const notificationLogicProps = { alertId: alert.id }
    const { isAlertFormSubmitting, alertFormChanged, alertFormErrors, alertForm } = useValues(
        logsAlertFormLogic(formLogicProps)
    )
    const { touchAlertFormField } = useActions(logsAlertFormLogic(formLogicProps))
    const { destinationGroups } = useValues(logsAlertNotificationLogic(notificationLogicProps))
    const { snoozingAlertIds } = useValues(logsAlertingLogic)
    const { deleteAlert, snoozeAlertUntil, toggleAlertEnabled, unsnoozeAlert } = useActions(logsAlertingLogic)
    const nameError = alertFormErrors.name as string | undefined
    const filterParts: string[] = []
    if (alertForm.severityLevels.length > 0) {
        filterParts.push(`${alertForm.severityLevels.join(', ')} logs`)
    }
    if (alertForm.serviceNames.length > 0) {
        filterParts.push(`from ${alertForm.serviceNames.join(', ')}`)
    }
    if (alertForm.filterGroup.values.length > 0) {
        const attributeCount = alertForm.filterGroup.values.length
        filterParts.push(`${attributeCount} ${attributeCount === 1 ? 'attribute filter' : 'attribute filters'}`)
    }
    const summary: AlertSummaryParts = {
        fires: `count ${alertForm.thresholdOperator} ${alertForm.thresholdCount} in the last ${alertForm.windowMinutes} minutes`,
        cadence: '',
        notifies: destinationGroups.length
            ? `${destinationGroups.length} ${destinationGroups.length === 1 ? 'destination' : 'destinations'}`
            : '',
        filters: filterParts.join(' '),
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
                    <AlertEditorFormDetails nameError={nameError} />
                    <div className="max-w-2xl space-y-6">
                        <LogsAlertFilters />
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
                    <LogsAlertTrigger />
                    <LogsAlertSimulation embedded />
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
                    <LogsAlertNotifications alertId={alert.id} />
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
                    <LogsAlertEventHistoryContent alert={alert} />
                </div>
            ),
        },
        {
            key: 'observed-logs',
            label: (
                <>
                    <IconList className="size-4" />
                    Observed logs
                </>
            ),
            link: urls.logsAlertDetail(alert.id, 'logs'),
        },
    ]

    const leadingActions = (
        <div className="flex flex-wrap items-center gap-2">
            <LemonButton
                type="secondary"
                status="danger"
                onClick={() => {
                    LemonDialog.open({
                        title: `Delete "${alert.name}"?`,
                        description: 'This alert will be permanently deleted. This action cannot be undone.',
                        primaryButton: {
                            children: 'Delete',
                            type: 'primary',
                            status: 'danger',
                            onClick: () => {
                                deleteAlert(alert.id, onClose)
                            },
                        },
                        secondaryButton: { children: 'Cancel' },
                    })
                }}
            >
                Delete alert
            </LemonButton>
            {(alert.enabled ?? true) ? (
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
        <BindLogic logic={logsAlertFormLogic} props={formLogicProps}>
            <BindLogic logic={logsAlertNotificationLogic} props={notificationLogicProps}>
                <Form
                    logic={logsAlertFormLogic}
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
                                checked={alert.enabled ?? true}
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
                                    <LogsAlertStateIndicator
                                        state={alert.state}
                                        enabled={alert.enabled ?? true}
                                        firstEnabledAt={alert.first_enabled_at}
                                        lastErrorMessage={alert.last_error_message}
                                        snoozeUntil={alert.snooze_until}
                                    />
                                </div>
                            }
                            statusNode={
                                <LogsAlertStateTimeline
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
        </BindLogic>
    )
}
