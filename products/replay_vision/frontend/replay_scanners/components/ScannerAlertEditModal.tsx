import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconBell, IconGraph, IconPulse, IconTarget } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { AlertEditor, AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'
import { AlertSummaryParts } from 'products/alerts/frontend/components/alertSummary'
import { SnoozeButton } from 'products/alerts/frontend/components/SnoozeButton'
import { EditAlertTab, EditAlertTabs } from 'products/alerts/frontend/views/EditAlertModal/EditAlertTabs'

import type { VisionAlertConfigurationApi } from '../../generated/api.schemas'
import { scannerAlertFormLogic } from '../scannerAlertFormLogic'
import { scannerAlertNotificationLogic } from '../scannerAlertNotificationLogic'
import { scannerAlertsLogic } from '../scannerAlertsLogic'
import { conditionSummary, selectionSummary } from '../scannerAlertUtils'
import { ScannerAlertEventHistory } from './ScannerAlertEventHistory'
import { ScannerAlertSelectionFields, ScannerAlertTrigger } from './ScannerAlertForm'
import { ScannerAlertNotifications } from './ScannerAlertNotifications'
import { ScannerAlertStateTag } from './ScannerAlertStateTag'

interface ScannerAlertEditModalProps {
    scannerId: string
    scannerType?: string
    alert: VisionAlertConfigurationApi | null
    onClose: () => void
}

export function ScannerAlertEditModal({
    scannerId,
    scannerType,
    alert,
    onClose,
}: ScannerAlertEditModalProps): JSX.Element {
    return (
        <LemonModal isOpen={alert !== null} onClose={onClose} title="" simple width={900}>
            {alert ? (
                <ScannerAlertEditModalContent
                    scannerId={scannerId}
                    scannerType={scannerType}
                    alert={alert}
                    onClose={onClose}
                />
            ) : null}
        </LemonModal>
    )
}

function ScannerAlertEditModalContent({
    scannerId,
    scannerType,
    alert,
    onClose,
}: {
    scannerId: string
    scannerType?: string
    alert: VisionAlertConfigurationApi
    onClose: () => void
}): JSX.Element {
    const formLogicProps = { scannerId, alert, onSubmitSuccess: onClose }
    const notificationLogicProps = { alertId: alert.id }
    const { isAlertFormSubmitting, alertFormChanged, alertFormErrors } = useValues(
        scannerAlertFormLogic(formLogicProps)
    )
    const { touchAlertFormField } = useActions(scannerAlertFormLogic(formLogicProps))
    const { destinationGroups } = useValues(scannerAlertNotificationLogic(notificationLogicProps))
    const { busyAlertIds } = useValues(scannerAlertsLogic({ scannerId }))
    const { deleteAlert, snoozeAlertUntil, toggleAlertEnabled, unsnoozeAlert } = useActions(
        scannerAlertsLogic({ scannerId })
    )
    const nameError = alertFormErrors.name as string | undefined

    const summary: AlertSummaryParts = {
        fires: conditionSummary(alert),
        cadence: '',
        notifies: destinationGroups.length
            ? `${destinationGroups.length} ${destinationGroups.length === 1 ? 'destination' : 'destinations'}`
            : '',
        filters: selectionSummary(alert),
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
                        <ScannerAlertSelectionFields scannerType={scannerType} />
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
                    <ScannerAlertTrigger />
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
                    <ScannerAlertNotifications />
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
                    <ScannerAlertEventHistory alert={alert} />
                </div>
            ),
        },
    ]

    const leadingActions = (
        <div className="flex flex-wrap items-center gap-2">
            <LemonButton
                type="secondary"
                status="danger"
                data-attr="vision-alert-delete"
                onClick={() => {
                    LemonDialog.open({
                        title: `Delete "${alert.name}"?`,
                        description:
                            'This alert and its notification destinations will be permanently deleted. This cannot be undone.',
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
                    disabledReason={busyAlertIds.has(alert.id) ? 'Updating snooze' : undefined}
                />
            ) : null}
        </div>
    )

    return (
        <BindLogic logic={scannerAlertFormLogic} props={formLogicProps}>
            <BindLogic logic={scannerAlertNotificationLogic} props={notificationLogicProps}>
                <Form
                    logic={scannerAlertFormLogic}
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
                                    <ScannerAlertStateTag alert={alert} />
                                </div>
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
