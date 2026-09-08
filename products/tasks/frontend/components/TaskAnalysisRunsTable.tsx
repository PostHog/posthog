import { useValues } from 'kea'

import { LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import type { LemonTableColumn } from 'lib/lemon-ui/LemonTable'

import { getEffortLabel, getModelLabel } from 'products/posthog_ai/frontend/utils/composerModels'

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

const STATUS_LABEL: Record<TaskRunStatusEnumApi, string> = {
    not_started: 'Not started',
    queued: 'Queued',
    in_progress: 'In progress',
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Canceled',
}

const ERROR_COLUMN: LemonTableColumn<TaskAnalysisRunApi, 'error_message'> = {
    title: 'Error',
    dataIndex: 'error_message',
    render: (_, run) =>
        run.error_message ? (
            <Tooltip title={run.error_message}>
                <span className="text-danger line-clamp-2">{run.error_message}</span>
            </Tooltip>
        ) : null,
}

export function TaskAnalysisRunsTable(): JSX.Element {
    const { catalogue, runs, runsLoading } = useValues(taskAnalysisSceneLogic)

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
                        <LemonTag type={STATUS_TAG_TYPE[run.status]}>{STATUS_LABEL[run.status]}</LemonTag>
                    ),
                },
                {
                    title: 'Model',
                    dataIndex: 'model',
                    render: (_, run: TaskAnalysisRunApi) =>
                        run.model ? (
                            <div className="flex flex-col">
                                <span className="whitespace-nowrap">{getModelLabel(catalogue, run.model)}</span>
                                {run.reasoning_effort ? (
                                    <span className="text-secondary text-xs">
                                        {getEffortLabel(run.reasoning_effort)} effort
                                    </span>
                                ) : null}
                            </div>
                        ) : (
                            <span className="text-secondary whitespace-nowrap">Built-in model</span>
                        ),
                },
                {
                    title: 'Analyzed run',
                    dataIndex: 'target_run_id',
                    render: (_, run: TaskAnalysisRunApi) => (
                        <div className="flex flex-col">
                            {run.target_repository ? (
                                <span className="whitespace-nowrap">{run.target_repository}</span>
                            ) : null}
                            {run.target_run_id ? (
                                <Tooltip title={run.target_run_id}>
                                    <span
                                        className={
                                            run.target_repository
                                                ? 'text-secondary font-mono text-xs'
                                                : 'font-mono text-xs'
                                        }
                                    >
                                        {run.target_run_id.slice(0, 8)}
                                    </span>
                                </Tooltip>
                            ) : null}
                        </div>
                    ),
                },
                {
                    title: 'Activities',
                    dataIndex: 'activities',
                    align: 'right',
                    render: (_, run: TaskAnalysisRunApi) =>
                        run.activities.length ? run.activities.length : <span className="text-secondary">0</span>,
                },
                // The column costs a third of the table width, so it appears only when a run failed.
                ...(runs?.some((run) => run.error_message) ? [ERROR_COLUMN] : []),
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
