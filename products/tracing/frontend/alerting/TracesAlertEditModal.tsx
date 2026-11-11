import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'

import { PlatformAlertDestinations } from 'products/alerts_platform/frontend/destinations/PlatformAlertDestinations'
import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { confirmDeleteTracesAlert } from './confirmDeleteTracesAlert'
import { TracesAlertFilterFields } from './TracesAlertFilterFields'
import { tracesAlertFormLogic } from './tracesAlertFormLogic'
import { tracesAlertsLogic } from './tracesAlertsLogic'
import { TracesAlertTriggerFields } from './TracesAlertTriggerFields'
import { alertDestinations, errorText } from './tracesAlertUtils'

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
    const { isAlertFormSubmitting, alertFormChanged, alertFormErrors } = useValues(tracesAlertFormLogic(formLogicProps))
    const { deleteAlert } = useActions(tracesAlertsLogic)

    return (
        <BindLogic logic={tracesAlertFormLogic} props={formLogicProps}>
            <Form
                logic={tracesAlertFormLogic}
                props={formLogicProps}
                formKey="alertForm"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <LemonModal.Header>
                    <h3 className="m-0">Edit traces alert</h3>
                </LemonModal.Header>
                <LemonModal.Content>
                    <div className="max-w-2xl space-y-4">
                        <TracesAlertFilterFields nameError={errorText(alertFormErrors.name)} />
                        <LemonDivider />
                        <TracesAlertTriggerFields thresholdError={errorText(alertFormErrors.threshold)} />
                        <LemonDivider />
                        <div className="space-y-2">
                            <h4 className="m-0">Destinations</h4>
                            <p className="text-sm text-secondary m-0">
                                Destinations are added and removed right away, without saving.
                            </p>
                            <PlatformAlertDestinations {...alertDestinations(alert.id)} />
                        </div>
                    </div>
                </LemonModal.Content>
                <LemonModal.Footer>
                    <div className="flex flex-1 flex-wrap items-center justify-between gap-2">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => confirmDeleteTracesAlert(alert, () => deleteAlert(alert))}
                            data-attr="traces-alert-edit-delete"
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
                                data-attr="traces-alert-edit-save"
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
