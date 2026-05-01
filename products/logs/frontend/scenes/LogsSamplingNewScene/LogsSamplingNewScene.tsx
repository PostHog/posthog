import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LogsSamplingForm } from 'products/logs/frontend/components/LogsSampling/LogsSamplingForm'
import { logsSamplingFormLogic } from 'products/logs/frontend/components/LogsSampling/logsSamplingFormLogic'

import { logsSamplingNewSceneLogic } from './logsSamplingNewSceneLogic'

const FORM_PROPS = { rule: null }

export const scene: SceneExport = {
    component: LogsSamplingNewScene,
    logic: logsSamplingNewSceneLogic,
}

export function LogsSamplingNewScene(): JSX.Element {
    const { samplingForm, isSamplingFormSubmitting } = useValues(logsSamplingFormLogic(FORM_PROPS))
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic(FORM_PROPS))

    return (
        <BindLogic logic={logsSamplingFormLogic} props={FORM_PROPS}>
            <SceneContent>
                <SceneTitleSection
                    name={samplingForm.name || 'New sampling rule'}
                    resourceType={{ type: 'logs' }}
                    canEdit
                    onNameChange={(name) => setSamplingFormValue('name', name)}
                    renameDebounceMs={0}
                />
                <div className="flex flex-col gap-6 p-4">
                    <Form logic={logsSamplingFormLogic} props={FORM_PROPS} formKey="samplingForm" enableFormOnSubmit>
                        <LogsSamplingForm />
                        <LemonButton
                            className="mt-4"
                            type="primary"
                            htmlType="submit"
                            loading={isSamplingFormSubmitting}
                        >
                            Save rule
                        </LemonButton>
                    </Form>
                </div>
            </SceneContent>
        </BindLogic>
    )
}
