import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'
import { compactNumber } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LogsSamplingForm } from 'products/logs/frontend/components/LogsSampling/LogsSamplingForm'
import { logsSamplingFormLogic } from 'products/logs/frontend/components/LogsSampling/logsSamplingFormLogic'
import { LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsSamplingDetailSceneLogicProps, logsSamplingDetailSceneLogic } from './logsSamplingDetailSceneLogic'

export const scene: SceneExport<LogsSamplingDetailSceneLogicProps> = {
    component: LogsSamplingDetailScene,
    logic: logsSamplingDetailSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function LogsSamplingDetailScene(): JSX.Element {
    const { rule, ruleLoading } = useValues(logsSamplingDetailSceneLogic)

    if (!rule && !ruleLoading) {
        return (
            <SceneContent>
                <div className="p-8 text-muted text-center">Drop rule not found.</div>
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

    const formProps = { rule }

    return (
        <BindLogic logic={logsSamplingFormLogic} props={formProps}>
            <LogsSamplingDetailFormBody rule={rule} />
        </BindLogic>
    )
}

function LogsSamplingDetailFormBody({ rule }: { rule: LogsSamplingRuleApi }): JSX.Element {
    const formProps = { rule }
    const { deleteRule } = useActions(logsSamplingDetailSceneLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic(formProps))
    const { samplingForm, isSamplingFormSubmitting } = useValues(logsSamplingFormLogic(formProps))
    const { ruleDropImpact24h, ruleDropImpact24hLoading } = useValues(logsSamplingDetailSceneLogic)

    const confirmDelete = (): void => {
        LemonDialog.open({
            title: 'Delete drop rule?',
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
            <SceneTitleSection
                name={samplingForm.name || rule.name}
                resourceType={{ type: 'logs' }}
                canEdit
                onNameChange={(name) => setSamplingFormValue('name', name)}
                renameDebounceMs={0}
                actions={
                    <LemonButton type="secondary" status="danger" onClick={confirmDelete}>
                        Delete
                    </LemonButton>
                }
            />
            <div className="px-4 pt-2 pb-0 text-secondary text-sm flex items-center gap-1.5">
                {ruleDropImpact24hLoading ? (
                    <span className="text-muted">Loading drop impact…</span>
                ) : ruleDropImpact24h === null ? (
                    <span className="text-muted" title="Drop impact for the last 24 hours is not available">
                        —
                    </span>
                ) : (
                    <>
                        <span>
                            ~{compactNumber(ruleDropImpact24h)} log lines dropped in the last 24 hours (ingestion).
                        </span>
                        <Tooltip
                            title={
                                <>
                                    From app metrics keyed by this rule. Service-scoped rules only affect that service;
                                    others are counted across the project.
                                </>
                            }
                        >
                            <IconInfo className="text-muted-alt text-base shrink-0" />
                        </Tooltip>
                    </>
                )}
            </div>
            <div className="flex flex-col gap-6 p-4">
                <Form logic={logsSamplingFormLogic} props={formProps} formKey="samplingForm" enableFormOnSubmit>
                    <LogsSamplingForm />
                    <LemonButton className="mt-4" type="primary" htmlType="submit" loading={isSamplingFormSubmitting}>
                        Save changes
                    </LemonButton>
                </Form>
            </div>
        </SceneContent>
    )
}
