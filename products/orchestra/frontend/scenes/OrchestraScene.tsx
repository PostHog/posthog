import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { orchestraLogic, OrchestraExecution } from '../logics/orchestraLogic'

export const scene: SceneExport = {
    component: OrchestraScene,
    logic: orchestraLogic,
}

function StatusTag({ status }: { status: string }): JSX.Element {
    const type = status === 'COMPLETED' ? 'success' : status === 'FAILED' ? 'danger' : 'default'
    return <LemonTag type={type}>{status}</LemonTag>
}

function OrchestraScene(): JSX.Element {
    const { executions, executionsLoading, statusFilter } = useValues(orchestraLogic)
    const { loadExecutions, setStatusFilter } = useActions(orchestraLogic)

    const columns: LemonTableColumns<OrchestraExecution> = [
        {
            title: 'Execution ID',
            dataIndex: 'execution_id',
            render: (_, record) => (
                <a href={urls.orchestraExecution(record.execution_id)}>{record.execution_id}</a>
            ),
        },
        {
            title: 'Type',
            dataIndex: 'execution_type',
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: (_, record) => <StatusTag status={record.status} />,
        },
        {
            title: 'Started',
            dataIndex: 'started_at',
            render: (_, record) => dayjs(record.started_at).fromNow(),
        },
        {
            title: 'Duration',
            render: (_, record) => {
                if (!record.finished_at) {
                    return 'Running...'
                }
                const duration = dayjs(record.finished_at).diff(dayjs(record.started_at), 'second')
                return `${duration}s`
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Orchestra"
                description="Workflow execution engine"
                resourceType={{ type: 'orchestra' }}
            />
            <div className="flex items-center gap-2 mb-4">
                <LemonSelect
                    value={statusFilter}
                    onChange={setStatusFilter}
                    options={[
                        { value: null, label: 'All statuses' },
                        { value: 'RUNNING', label: 'Running' },
                        { value: 'COMPLETED', label: 'Completed' },
                        { value: 'FAILED', label: 'Failed' },
                    ]}
                    size="small"
                />
                <LemonButton type="secondary" size="small" onClick={loadExecutions}>
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={executions}
                loading={executionsLoading}
                emptyState="No executions found"
                onRow={(record) => ({
                    onClick: () => {
                        window.location.href = urls.orchestraExecution(record.execution_id)
                    },
                })}
            />
        </SceneContent>
    )
}
