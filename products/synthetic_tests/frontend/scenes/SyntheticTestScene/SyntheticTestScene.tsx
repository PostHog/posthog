import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonButton,
    LemonCollapse,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTable,
    LemonTag,
    LemonTagType,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Field } from 'lib/forms/Field'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StepBuilder } from '../../components/StepBuilder/StepBuilder'
import { SCHEDULE_PRESETS } from '../../types'
import { syntheticTestSceneLogic, SyntheticTestSceneProps } from './syntheticTestSceneLogic'

const STATUS_TAG: Record<string, { type: LemonTagType; label: string }> = {
    passed: { type: 'success', label: 'Passed' },
    failed: { type: 'danger', label: 'Failed' },
    running: { type: 'primary', label: 'Running' },
    timeout: { type: 'warning', label: 'Timeout' },
    error: { type: 'danger', label: 'Error' },
}

export function SyntheticTestScene({ id }: SyntheticTestSceneProps): JSX.Element {
    const logic = syntheticTestSceneLogic({ id })
    const { test, runs, runsLoading, isNew, testForm, playwrightScript } = useValues(logic)
    const { setSteps, runNow, submitTestForm } = useActions(logic)

    return (
        <SceneContent>
            <SceneTitleSection
                name={isNew ? 'New synthetic test' : (test?.name ?? 'Synthetic test')}
                description="Configure steps, schedule, and where failures get reported."
                resourceType={{ type: 'synthetic_tests' as any }}
                actions={
                    !isNew && (
                        <LemonButton type="primary" onClick={runNow} data-attr="synthetic-test-run-now-detail">
                            Run now
                        </LemonButton>
                    )
                }
            />
            <Form logic={syntheticTestSceneLogic} props={{ id }} formKey="testForm">
                <div className="flex flex-col gap-4 max-w-3xl">
                    <Field name="name" label="Name">
                        <LemonInput placeholder="Cloud signup smoke test" data-attr="synthetic-test-name" />
                    </Field>
                    <Field name="target_url" label="Target URL">
                        <LemonInput placeholder="https://us.posthog.com/signup" data-attr="synthetic-test-url" />
                    </Field>
                    {test?.source_replay_id && (
                        <div className="text-xs text-muted">
                            Seeded from{' '}
                            <Link to={`/replay/${test.source_replay_id}`} data-attr="source-replay-link">
                                session replay {test.source_replay_id.slice(0, 8)}…
                            </Link>
                        </div>
                    )}
                    <div>
                        <label className="font-semibold mb-2 block">Steps</label>
                        <StepBuilder steps={testForm.steps} onChange={setSteps} />
                    </div>
                    <Field name="schedule_cron" label="Schedule">
                        <LemonSelect
                            options={SCHEDULE_PRESETS.map((p) => ({ value: p.cron, label: p.label }))}
                            data-attr="synthetic-test-schedule"
                        />
                    </Field>
                    <Field name="create_issue_on_failure">
                        <LemonSwitch label="Open an Error Tracking issue on failure" bordered />
                    </Field>
                    <div className="flex gap-2">
                        <LemonButton type="primary" onClick={submitTestForm} data-attr="synthetic-test-save">
                            {isNew ? 'Create test' : 'Save changes'}
                        </LemonButton>
                    </div>
                </div>
            </Form>
            {!isNew && playwrightScript && (
                <section className="mt-6 max-w-3xl">
                    <LemonCollapse
                        panels={[
                            {
                                key: 'script',
                                header: 'Generated Playwright script',
                                content: (
                                    <pre className="text-xs bg-bg-light p-3 rounded overflow-x-auto">
                                        {playwrightScript}
                                    </pre>
                                ),
                            },
                        ]}
                    />
                </section>
            )}
            {!isNew && (
                <section className="mt-8">
                    <h3 className="font-semibold mb-2">Run history</h3>
                    <LemonTable
                        dataSource={runs}
                        loading={runsLoading}
                        rowKey="id"
                        emptyState="No runs yet — hit Run now or wait for the next scheduled tick."
                        columns={[
                            {
                                title: 'Started',
                                key: 'started_at',
                                render: (_, run) => <TZLabel time={run.started_at} />,
                            },
                            {
                                title: 'Status',
                                key: 'status',
                                render: (_, run) => {
                                    const s = STATUS_TAG[run.status] ?? {
                                        type: 'muted' as LemonTagType,
                                        label: run.status,
                                    }
                                    return <LemonTag type={s.type}>{s.label}</LemonTag>
                                },
                            },
                            {
                                title: 'Duration',
                                key: 'duration_ms',
                                render: (_, run) => (run.duration_ms != null ? `${run.duration_ms} ms` : '—'),
                            },
                            {
                                title: 'Error',
                                key: 'error_message',
                                render: (_, run) =>
                                    run.error_message ? (
                                        <span className="text-xs text-danger">
                                            step {run.error_step_index ?? '?'}: {run.error_message.slice(0, 120)}
                                        </span>
                                    ) : (
                                        <span className="text-muted">—</span>
                                    ),
                            },
                        ]}
                    />
                </section>
            )}
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SyntheticTestScene,
    logic: syntheticTestSceneLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }) => ({ id: id ?? 'new' }),
}

export default SyntheticTestScene
