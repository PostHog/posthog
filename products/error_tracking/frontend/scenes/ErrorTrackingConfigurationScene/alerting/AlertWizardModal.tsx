import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { AlertWizard } from 'scenes/hog-functions/AlertWizard/AlertWizard'
import { AlertCreationView, WizardStep, alertWizardLogic } from 'scenes/hog-functions/AlertWizard/alertWizardLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

import { buildErrorTrackingAlertWizardProps } from './errorTrackingAlertingConfig'

interface AlertWizardModalProps {
    isOpen: boolean
    onClose: () => void
    initialTriggerKey?: HogFunctionSubTemplateIdType
}

export function AlertWizardModal({ isOpen, onClose, initialTriggerKey }: AlertWizardModalProps): JSX.Element {
    if (!isOpen) {
        return <LemonModal isOpen={false} onClose={onClose} width={560} simple hideCloseButton />
    }

    const logicKey = `error-tracking-modal-${initialTriggerKey ?? 'default'}`
    const wizardProps = buildErrorTrackingAlertWizardProps({ logicKey, initialTriggerKey })

    return (
        <LemonModal isOpen onClose={onClose} width={560} simple hideCloseButton>
            <BindLogic logic={alertWizardLogic} props={wizardProps}>
                <AlertWizardModalInner onClose={onClose} hideTriggerStep={!!initialTriggerKey} />
            </BindLogic>
        </LemonModal>
    )
}

function AlertWizardModalInner({
    onClose,
    hideTriggerStep,
}: {
    onClose: () => void
    hideTriggerStep: boolean
}): JSX.Element {
    const { alertCreationView } = useValues(alertWizardLogic)
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)
    const enteredWizardRef = useRef(false)

    useEffect(() => {
        setAlertCreationView(AlertCreationView.Wizard)
    }, [setAlertCreationView])

    useEffect(() => {
        if (alertCreationView === AlertCreationView.Wizard) {
            enteredWizardRef.current = true
        } else if (alertCreationView === AlertCreationView.None && enteredWizardRef.current) {
            onClose()
        }
    }, [alertCreationView, onClose])

    return (
        <div className="p-4">
            <AlertWizard
                onCancel={() => {
                    resetWizard()
                    onClose()
                }}
                hiddenSteps={hideTriggerStep ? [WizardStep.Trigger] : undefined}
            />
        </div>
    )
}
