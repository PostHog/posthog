import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LogsRetentionForm } from 'products/logs/frontend/components/LogsRetention/LogsRetentionForm'
import { logsRetentionFormLogic } from 'products/logs/frontend/components/LogsRetention/logsRetentionFormLogic'
import { retentionFormSaveDisabledReason } from 'products/logs/frontend/components/LogsRetention/retentionFormSaveDisabledReason'

import { logsRetentionNewSceneLogic } from './logsRetentionNewSceneLogic'

const FORM_PROPS = { rule: null }

export const scene: SceneExport = {
    component: LogsRetentionNewScene,
    logic: logsRetentionNewSceneLogic,
}

export function LogsRetentionNewScene(): JSX.Element {
    const { retentionForm, isRetentionFormSubmitting } = useValues(logsRetentionFormLogic(FORM_PROPS))
    const { setRetentionFormValue } = useActions(logsRetentionFormLogic(FORM_PROPS))
    const saveDisabledReason = retentionFormSaveDisabledReason(retentionForm)

    return (
        <BindLogic logic={logsRetentionFormLogic} props={FORM_PROPS}>
            <SceneContent>
                <Form logic={logsRetentionFormLogic} props={FORM_PROPS} formKey="retentionForm" enableFormOnSubmit>
                    <SceneTitleSection
                        name={retentionForm.name || 'New retention rule'}
                        resourceType={{ type: 'logs' }}
                        canEdit
                        onNameChange={(name) => setRetentionFormValue('name', name)}
                        renameDebounceMs={0}
                    />
                    <SceneStickyBar>
                        <div className="flex justify-end gap-2">
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isRetentionFormSubmitting}
                                disabledReason={saveDisabledReason ?? undefined}
                            >
                                Save retention rule
                            </LemonButton>
                        </div>
                    </SceneStickyBar>
                    <div className="flex flex-col gap-6 p-4">
                        <LogsRetentionForm />
                    </div>
                </Form>
            </SceneContent>
        </BindLogic>
    )
}
