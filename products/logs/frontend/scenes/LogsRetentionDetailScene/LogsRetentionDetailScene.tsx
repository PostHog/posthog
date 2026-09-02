import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LogsRetentionForm } from 'products/logs/frontend/components/LogsRetention/LogsRetentionForm'
import { logsRetentionFormLogic } from 'products/logs/frontend/components/LogsRetention/logsRetentionFormLogic'
import { retentionFormSaveDisabledReason } from 'products/logs/frontend/components/LogsRetention/retentionFormSaveDisabledReason'
import { LogsRetentionRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsRetentionDetailSceneLogicProps, logsRetentionDetailSceneLogic } from './logsRetentionDetailSceneLogic'

export const scene: SceneExport<LogsRetentionDetailSceneLogicProps> = {
    component: LogsRetentionDetailScene,
    logic: logsRetentionDetailSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function LogsRetentionDetailScene(): JSX.Element {
    const { rule, ruleLoading } = useValues(logsRetentionDetailSceneLogic)

    if (!rule && !ruleLoading) {
        return (
            <SceneContent>
                <div className="p-8 text-muted text-center">Retention rule not found.</div>
            </SceneContent>
        )
    }

    if (!rule) {
        return (
            <SceneContent>
                <div className="p-8 text-muted text-center">Loading…</div>
            </SceneContent>
        )
    }

    return (
        <BindLogic logic={logsRetentionFormLogic} props={{ rule }}>
            <LogsRetentionDetailFormBody rule={rule} />
        </BindLogic>
    )
}

function LogsRetentionDetailFormBody({ rule }: { rule: LogsRetentionRuleApi }): JSX.Element {
    const formProps = { rule }
    const { deleteRule } = useActions(logsRetentionDetailSceneLogic)
    const { setRetentionFormValue } = useActions(logsRetentionFormLogic(formProps))
    const { retentionForm, isRetentionFormSubmitting } = useValues(logsRetentionFormLogic(formProps))
    const saveDisabledReason = retentionFormSaveDisabledReason(retentionForm)

    const confirmDelete = (): void => {
        LemonDialog.open({
            title: 'Delete retention rule?',
            description:
                'This cannot be undone. In-flight ingestion workers may briefly still use a cached copy of the rule.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteRule(),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <SceneContent>
            <Form logic={logsRetentionFormLogic} props={formProps} formKey="retentionForm" enableFormOnSubmit>
                <SceneTitleSection
                    name={retentionForm.name || rule.name}
                    resourceType={{ type: 'logs' }}
                    canEdit
                    onNameChange={(name) => setRetentionFormValue('name', name)}
                    renameDebounceMs={0}
                    actions={
                        <LemonButton type="secondary" status="danger" onClick={confirmDelete}>
                            Delete
                        </LemonButton>
                    }
                />
                <SceneStickyBar>
                    <div className="flex justify-end gap-2">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isRetentionFormSubmitting}
                            disabledReason={saveDisabledReason ?? undefined}
                        >
                            Save changes
                        </LemonButton>
                    </div>
                </SceneStickyBar>
                <div className="flex flex-col gap-6 p-4">
                    <LogsRetentionForm />
                </div>
            </Form>
        </SceneContent>
    )
}
