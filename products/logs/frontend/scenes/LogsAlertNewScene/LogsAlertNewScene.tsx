import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTestTube } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LogsAlertForm } from 'products/logs/frontend/components/LogsAlerting/LogsAlertForm'
import { logsAlertFormLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertFormLogic'
import { LogsAlertSimulation } from 'products/logs/frontend/components/LogsAlerting/LogsAlertSimulation'

import { logsAlertNewSceneLogic } from './logsAlertNewSceneLogic'

export const scene: SceneExport = {
    component: LogsAlertNewScene,
    logic: logsAlertNewSceneLogic,
}

const FORM_PROPS = { alert: null }

export function LogsAlertNewScene(): JSX.Element {
    const { canCreateDraft, createdAlertLoading } = useValues(logsAlertNewSceneLogic)
    const { createDraft } = useActions(logsAlertNewSceneLogic)
    const { alertForm, isSimulationPanelOpen } = useValues(logsAlertFormLogic(FORM_PROPS))
    const { setAlertFormValue, openSimulationPanel, closeSimulationPanel } = useActions(logsAlertFormLogic(FORM_PROPS))

    return (
        <BindLogic logic={logsAlertFormLogic} props={FORM_PROPS}>
            <SceneContent>
                <SceneTitleSection
                    name={alertForm.name || 'New alert'}
                    resourceType={{ type: 'logs' }}
                    canEdit
                    onNameChange={(name) => setAlertFormValue('name', name)}
                    renameDebounceMs={0}
                    actions={
                        <div className="flex items-center gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconTestTube />}
                                onClick={openSimulationPanel}
                                active={isSimulationPanelOpen}
                                tooltip="Run this alert against historical data to see when it would have fired"
                            >
                                Simulate
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={createDraft}
                                loading={createdAlertLoading}
                                disabledReason={
                                    !canCreateDraft ? 'Add a name and at least one filter to create' : undefined
                                }
                            >
                                Create draft
                            </LemonButton>
                        </div>
                    }
                />
                <div className="flex flex-col gap-6 p-4">
                    <Form logic={logsAlertFormLogic} props={FORM_PROPS} formKey="alertForm" enableFormOnSubmit>
                        <LogsAlertForm />
                    </Form>
                </div>
                <LemonModal
                    isOpen={isSimulationPanelOpen}
                    onClose={closeSimulationPanel}
                    title="Alert simulation"
                    description="Run the alert against historical data to preview when it would have fired. Includes threshold evaluation, N-of-M noise reduction, and cooldown."
                    width={960}
                >
                    <LogsAlertSimulation />
                </LemonModal>
            </SceneContent>
        </BindLogic>
    )
}
