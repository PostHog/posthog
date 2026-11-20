import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'

import { PlatformAlertNotifications } from 'products/alerts_platform/frontend/destinations/PlatformAlertNotifications'
import {
    PlatformAlertConfigurationApi,
    PlatformAlertConfigurationSourceKindEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import { confirmDeleteMetricsAlert } from './confirmDeleteMetricsAlert'
import { metricsAlertFormLogic } from './metricsAlertFormLogic'
import { metricsAlertingLogic } from './metricsAlertingLogic'
import { MetricsAlertQueryFields } from './MetricsAlertQueryFields'
import { MetricsAlertTriggerFields } from './MetricsAlertTriggerFields'
import { MetricsAlertFormErrors } from './metricsAlertUtils'

interface MetricsAlertEditModalProps {
    alert: PlatformAlertConfigurationApi | null
    onClose: () => void
}

export function MetricsAlertEditModal({ alert, onClose }: MetricsAlertEditModalProps): JSX.Element {
    return (
        <LemonModal isOpen={alert !== null} onClose={onClose} title="" simple width={900}>
            {alert ? <MetricsAlertEditModalContent alert={alert} onClose={onClose} /> : null}
        </LemonModal>
    )
}

function MetricsAlertEditModalContent({
    alert,
    onClose,
}: {
    alert: PlatformAlertConfigurationApi
    onClose: () => void
}): JSX.Element {
    const formLogicProps = { alert, onSubmitSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, alertFormErrors } = useValues(
        metricsAlertFormLogic(formLogicProps)
    )
    const { deleteAlert } = useActions(metricsAlertingLogic)
    // kea-forms fills these only after a save attempt, so a fresh modal shows no errors.
    const errors = alertFormErrors as MetricsAlertFormErrors

    return (
        <BindLogic logic={metricsAlertFormLogic} props={formLogicProps}>
            <Form
                logic={metricsAlertFormLogic}
                props={formLogicProps}
                formKey="alertForm"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <LemonModal.Header>
                    <h3 className="m-0">Edit metrics alert</h3>
                </LemonModal.Header>
                <LemonModal.Content>
                    <div className="max-w-2xl space-y-4">
                        <MetricsAlertQueryFields nameError={errors.name} queryError={errors.query} />
                        <LemonDivider />
                        <MetricsAlertTriggerFields thresholdError={errors.threshold} />
                        <LemonDivider />
                        <div className="space-y-2">
                            <h4 className="m-0">Notifications</h4>
                            <PlatformAlertNotifications
                                alertId={alert.id}
                                sourceKind={PlatformAlertConfigurationSourceKindEnumApi.Metrics}
                            />
                        </div>
                    </div>
                </LemonModal.Content>
                <LemonModal.Footer>
                    <div className="flex flex-1 flex-wrap items-center justify-between gap-2">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => confirmDeleteMetricsAlert(alert, () => deleteAlert(alert))}
                            data-attr="metrics-alert-edit-delete"
                        >
                            Delete
                        </LemonButton>
                        <div className="flex gap-2">
                            <LemonButton type="secondary" onClick={onClose}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isAlertFormSubmitting}
                                disabledReason={alertFormChanged ? undefined : 'No changes to save'}
                                data-attr="metrics-alert-edit-save"
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>
                </LemonModal.Footer>
            </Form>
        </BindLogic>
    )
}
