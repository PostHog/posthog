import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SyntheticTest } from '../../types'
import { syntheticTestsSceneLogic } from './syntheticTestsSceneLogic'

const STATUS_TAG: Record<string, { type: LemonTagType; label: string }> = {
    passed: { type: 'success', label: 'Passing' },
    failed: { type: 'danger', label: 'Failing' },
    running: { type: 'primary', label: 'Running' },
    timeout: { type: 'warning', label: 'Timeout' },
    error: { type: 'danger', label: 'Error' },
}

function statusFor(test: SyntheticTest): { type: LemonTagType; label: string } {
    if (test.status === 'paused') {
        return { type: 'muted', label: 'Paused' }
    }
    if (!test.last_run) {
        return { type: 'muted', label: 'Pending' }
    }
    return STATUS_TAG[test.last_run.status] ?? { type: 'muted', label: test.last_run.status }
}

export function SyntheticTestsScene(): JSX.Element {
    const { tests, testsLoading, passingCount, failingCount } = useValues(syntheticTestsSceneLogic)
    const { deleteTest, runNow, pauseTest, resumeTest } = useActions(syntheticTestsSceneLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Synthetic tests"
                description="Scheduled browser checks against your product. Build them by hand or seed from a session replay."
                resourceType={{ type: 'synthetic_tests' as any }}
                actions={
                    <LemonButton type="primary" to={(urls as any).syntheticTestNew()} data-attr="synthetic-tests-new">
                        New test
                    </LemonButton>
                }
            />
            <div className="flex gap-4 mb-4 text-sm">
                <span>
                    <strong>{passingCount}</strong> passing
                </span>
                <span>
                    <strong>{failingCount}</strong> failing
                </span>
                <span>
                    <strong>{tests.length}</strong> total
                </span>
            </div>
            <LemonTable
                dataSource={tests}
                loading={testsLoading}
                rowKey="id"
                emptyState="No synthetic tests yet — create one or save a session replay as a test."
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, test) => (
                            <Link to={(urls as any).syntheticTest(test.id)} data-attr="synthetic-test-row-link">
                                {test.name}
                            </Link>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, test) => {
                            const status = statusFor(test)
                            return (
                                <Tooltip title={test.last_run?.error_message || ''}>
                                    <LemonTag type={status.type}>{status.label}</LemonTag>
                                </Tooltip>
                            )
                        },
                    },
                    {
                        title: 'Schedule',
                        key: 'schedule',
                        render: (_, test) => <code className="text-xs">{test.schedule_cron}</code>,
                    },
                    {
                        title: 'Last run',
                        key: 'last_run',
                        render: (_, test) =>
                            test.last_run_at ? (
                                <TZLabel time={test.last_run_at} />
                            ) : (
                                <span className="text-muted">—</span>
                            ),
                    },
                    {
                        title: 'Next run',
                        key: 'next_run',
                        render: (_, test) =>
                            test.next_run_at ? (
                                <TZLabel time={test.next_run_at} />
                            ) : (
                                <span className="text-muted">—</span>
                            ),
                    },
                    {
                        title: '',
                        key: 'actions',
                        render: (_, test) => (
                            <div className="flex gap-1">
                                <LemonButton
                                    size="xsmall"
                                    onClick={() => runNow(test.id)}
                                    data-attr="synthetic-test-run-now"
                                >
                                    Run now
                                </LemonButton>
                                {test.status === 'active' ? (
                                    <LemonButton size="xsmall" onClick={() => pauseTest(test.id)}>
                                        Pause
                                    </LemonButton>
                                ) : (
                                    <LemonButton size="xsmall" onClick={() => resumeTest(test.id)}>
                                        Resume
                                    </LemonButton>
                                )}
                                <LemonButton
                                    size="xsmall"
                                    status="danger"
                                    onClick={() => deleteTest(test.id)}
                                    data-attr="synthetic-test-delete"
                                >
                                    Delete
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
            />
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SyntheticTestsScene,
    logic: syntheticTestsSceneLogic,
}

export default SyntheticTestsScene
