import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { LemonButton, LemonDialog, LemonModal, LemonSwitch, LemonTabs } from '@posthog/lemon-ui'

import { AlertEditor } from 'products/alerts/frontend/components/AlertEditor'
import { SnoozeButton } from 'products/alerts/frontend/components/SnoozeButton'
import {
    LogsAlertConfigurationStateEnumApi as TracingAlertConfigurationStateEnumApi,
    TracingAlertConfigurationApi,
} from 'products/tracing/frontend/generated/api.schemas'

import { TracingAlertEventHistoryContent } from './TracingAlertEventHistory'
import { TracingAlertForm } from './TracingAlertForm'
import { tracingAlertFormLogic } from './tracingAlertFormLogic'
import { tracingAlertingLogic } from './tracingAlertingLogic'

export function TracingAlertEditModal({
    alert,
    onClose,
}: {
    alert: TracingAlertConfigurationApi | null
    onClose: () => void
}): JSX.Element {
    return (
        <LemonModal isOpen={alert !== null} onClose={onClose} width={800} title="">
            {alert ? <TracingAlertEditModalContent alert={alert} onClose={onClose} /> : null}
        </LemonModal>
    )
}

function TracingAlertEditModalContent({
    alert,
    onClose,
}: {
    alert: TracingAlertConfigurationApi
    onClose: () => void
}): JSX.Element {
    const logicProps = { alert, onSubmitSuccess: onClose }
    const { alertFormChanged, isAlertFormSubmitting } = useValues(tracingAlertFormLogic(logicProps))
    const { deletingAlertIds, snoozingAlertIds, togglingAlertIds } = useValues(tracingAlertingLogic)
    const { deleteAlert, toggleAlertEnabled, snoozeAlertUntil, unsnoozeAlert } = useActions(tracingAlertingLogic)
    const [activeTab, setActiveTab] = useState<'definition' | 'history'>('definition')

    return (
        <Form logic={tracingAlertFormLogic} props={logicProps} formKey="alertForm" enableFormOnSubmit>
            <AlertEditor
                title={alert.name || 'Untitled alert'}
                description="Get notified when traces cross a threshold you define."
                isEditing
                isSubmitting={isAlertFormSubmitting}
                hasChanges={alertFormChanged}
                leadingActions={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            disabledReason={deletingAlertIds.has(alert.id) ? 'Deleting…' : undefined}
                            onClick={() => {
                                LemonDialog.open({
                                    title: `Delete "${alert.name}"?`,
                                    description:
                                        'This alert will be permanently deleted. This action cannot be undone.',
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        status: 'danger',
                                        disabledReason: deletingAlertIds.has(alert.id) ? 'Deleting…' : undefined,
                                        onClick: () => deleteAlert(alert.id, onClose),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Delete
                        </LemonButton>
                        {alert.state === TracingAlertConfigurationStateEnumApi.Snoozed ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => unsnoozeAlert(alert.id)}
                                disabledReason={snoozingAlertIds.has(alert.id) ? 'Updating snooze' : undefined}
                            >
                                Unsnooze
                            </LemonButton>
                        ) : (
                            <SnoozeButton
                                onChange={(snoozeUntil) => snoozeAlertUntil(alert.id, snoozeUntil)}
                                disabledReason={snoozingAlertIds.has(alert.id) ? 'Updating snooze' : undefined}
                            />
                        )}
                    </div>
                }
                trailingActions={
                    <LemonSwitch
                        checked={alert.enabled === true}
                        onChange={() => toggleAlertEnabled(alert)}
                        disabledReason={
                            alert.state === TracingAlertConfigurationStateEnumApi.Broken
                                ? 'Reset this alert to re-enable checks'
                                : togglingAlertIds.has(alert.id)
                                  ? 'Updating…'
                                  : undefined
                        }
                        label="Enabled"
                        data-attr="tracing-alert-modal-toggle"
                    />
                }
            >
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as 'definition' | 'history')}
                    tabs={[
                        { key: 'definition', label: 'Definition', content: <TracingAlertForm /> },
                        {
                            key: 'history',
                            label: 'History',
                            content: <TracingAlertEventHistoryContent alert={alert} />,
                        },
                    ]}
                />
            </AlertEditor>
        </Form>
    )
}
