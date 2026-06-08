import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LogsSamplingForm } from 'products/logs/frontend/components/LogsSampling/LogsSamplingForm'
import { logsSamplingFormLogic } from 'products/logs/frontend/components/LogsSampling/logsSamplingFormLogic'
import { samplingFormSaveDisabledReason } from 'products/logs/frontend/components/LogsSampling/samplingFormSaveDisabledReason'

import { logsSamplingNewSceneLogic } from './logsSamplingNewSceneLogic'

const FORM_PROPS = { rule: null }

export const scene: SceneExport = {
    component: LogsSamplingNewScene,
    logic: logsSamplingNewSceneLogic,
}

export function LogsSamplingNewScene(): JSX.Element {
    const { samplingForm, isSamplingFormSubmitting } = useValues(logsSamplingFormLogic(FORM_PROPS))
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic(FORM_PROPS))
    const saveDisabledReason = samplingFormSaveDisabledReason(samplingForm)

    return (
        <BindLogic logic={logsSamplingFormLogic} props={FORM_PROPS}>
            <SceneContent>
                <Form logic={logsSamplingFormLogic} props={FORM_PROPS} formKey="samplingForm" enableFormOnSubmit>
                    <SceneTitleSection
                        name={samplingForm.name || 'New drop rule'}
                        resourceType={{ type: 'logs' }}
                        canEdit
                        onNameChange={(name) => setSamplingFormValue('name', name)}
                        renameDebounceMs={0}
                    />
                    <SceneStickyBar>
                        <div className="flex justify-end gap-2">
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isSamplingFormSubmitting}
                                disabledReason={saveDisabledReason ?? undefined}
                            >
                                Save drop rule
                            </LemonButton>
                        </div>
                    </SceneStickyBar>
                    <div className="flex flex-col gap-6 p-4">
                        <LogsSamplingForm />
                    </div>
                </Form>
            </SceneContent>
        </BindLogic>
    )
}
