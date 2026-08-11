import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTestTube } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AlertEditor, AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'

import { LogsAlertForm } from './LogsAlertForm'
import { logsAlertFormLogic } from './logsAlertFormLogic'
import { LogsAlertSimulation } from './LogsAlertSimulation'

interface LogsAlertCreateModalProps {
    isOpen: boolean
    onClose: () => void
}

export function LogsAlertCreateModal({ isOpen, onClose }: LogsAlertCreateModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="" simple width={720}>
            {isOpen ? <LogsAlertCreateModalContent onClose={onClose} /> : null}
        </LemonModal>
    )
}

function LogsAlertCreateModalContent({ onClose }: { onClose: () => void }): JSX.Element {
    const formLogicProps = { alert: null, onCreateSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, isSimulationPanelOpen } = useValues(
        logsAlertFormLogic(formLogicProps)
    )
    const { openSimulationPanel, closeSimulationPanel } = useActions(logsAlertFormLogic(formLogicProps))

    return (
        <BindLogic logic={logsAlertFormLogic} props={formLogicProps}>
            <Form
                logic={logsAlertFormLogic}
                props={formLogicProps}
                formKey="alertForm"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <AlertEditor
                    title="New alert"
                    description="Alerts are checked every 5 minutes."
                    onBack={onClose}
                    className="min-h-0 flex-1 overflow-hidden"
                    contentClassName="min-h-0 flex-1 overflow-y-auto"
                    isEditing={false}
                    isSubmitting={isAlertFormSubmitting}
                    hasChanges={alertFormChanged}
                    leadingActions={
                        <LemonButton
                            type="secondary"
                            icon={<IconTestTube />}
                            onClick={openSimulationPanel}
                            tooltip="Run this alert against historical data to see when it would have fired"
                        >
                            Simulate
                        </LemonButton>
                    }
                >
                    <div className="max-w-2xl space-y-6">
                        <AlertEditorFormDetails />
                        <LogsAlertForm />
                    </div>
                </AlertEditor>
            </Form>

            <LemonModal
                isOpen={isSimulationPanelOpen}
                onClose={closeSimulationPanel}
                title="Alert simulation"
                description="Run the alert against historical data to preview when it would have fired. Includes threshold evaluation, N-of-M noise reduction, and cooldown."
                width={960}
            >
                <LogsAlertSimulation />
            </LemonModal>
        </BindLogic>
    )
}
