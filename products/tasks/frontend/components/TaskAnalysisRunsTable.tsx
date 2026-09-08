import { useValues } from 'kea'

import { LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { TaskAnalysisRunApi, TaskRunStatusEnumApi } from '../generated/api.schemas'
import { taskAnalysisSceneLogic } from '../logics/taskAnalysisSceneLogic'
import { TaskAnalysisActivitiesTable } from './TaskAnalysisActivitiesTable'

const STATUS_TAG_TYPE: Record<TaskRunStatusEnumApi, LemonTagType> = {
    not_started: 'muted',
    queued: 'muted',
    in_progress: 'primary',
    completed: 'success',
    failed: 'danger',
    cancelled: 'default',
}

export function TaskAnalysisRunsTable(): JSX.Element {
    const { runs, runsLoading } = useValues(taskAnalysisSceneLogic)

    return (
        <LemonTable
            dataSource={runs ?? []}
            loading={runsLoading}
            rowKey="id"
            emptyState="No analysis runs yet. A run appears here after a task run is analyzed."
            columns={[
                {
                    title: 'Created',
                    dataIndex: 'created_at',
                    render: (_, run: TaskAnalysisRunApi) => <TZLabel time={run.created_at} />,
                },
                {
                    title: 'Status',
                    dataIndex: 'status',
                    render: (_, run: TaskAnalysisRunApi) => (
                        <LemonTag type={STATUS_TAG_TYPE[run.status]}>{run.status.replace('_', ' ')}</LemonTag>
                    ),
                },
                {
                    title: 'Model',
                    dataIndex: 'model',
                    render: (_, run: TaskAnalysisRunApi) => (
                        <div className="flex flex-col">
                            <span className="whitespace-nowrap">{run.model ?? 'Built-in'}</span>
                            {run.reasoning_effort ? (
                                <span className="text-secondary text-xs">{run.reasoning_effort}</span>
                            ) : null}
                        </div>
                    ),
                },
                {
                    title: 'Analyzed run',
                    dataIndex: 'target_run_id',
                    render: (_, run: TaskAnalysisRunApi) => (
                        <div className="flex flex-col">
                            <span className="font-mono text-xs break-all">{run.target_run_id ?? '–'}</span>
                            {run.target_repository ? (
                                <span className="text-secondary text-xs">{run.target_repository}</span>
                            ) : null}
                        </div>
                    ),
                },
                {
                    title: 'Activities',
                    dataIndex: 'activities',
                    align: 'right',
                    render: (_, run: TaskAnalysisRunApi) => run.activities.length,
                },
                {
                    title: 'Error',
                    dataIndex: 'error_message',
                    render: (_, run: TaskAnalysisRunApi) =>
                        run.error_message ? <span className="text-danger break-words">{run.error_message}</span> : null,
                },
            ]}
            expandable={{
                rowExpandable: (run: TaskAnalysisRunApi) => run.activities.length > 0,
                expandedRowRender: (run: TaskAnalysisRunApi) => (
                    <TaskAnalysisActivitiesTable activities={run.activities} />
                ),
            }}
        />
    )
}
