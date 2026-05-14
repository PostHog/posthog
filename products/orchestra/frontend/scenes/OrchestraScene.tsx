import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { OrchestraDeployment, OrchestraExecution, orchestraLogic } from '../logics/orchestraLogic'

export const scene: SceneExport = {
    component: OrchestraScene,
    logic: orchestraLogic,
}

function StatusTag({ status }: { status: string }): JSX.Element {
    const type = status === 'COMPLETED' ? 'success' : status === 'FAILED' ? 'danger' : 'default'
    return <LemonTag type={type}>{status}</LemonTag>
}

function DeploymentStatusTag({ status }: { status: string }): JSX.Element {
    const type =
        status === 'active' ? 'success' : status === 'draining' ? 'warning' : status === 'failed' ? 'danger' : 'default'
    return <LemonTag type={type}>{status}</LemonTag>
}

function ActiveDeploymentCard(): JSX.Element {
    const { activeDeployment, deployments, activeDeploymentLoading } = useValues(orchestraLogic)
    const { triggerGreeting } = useActions(orchestraLogic)

    return (
        <div className="border rounded p-4 mb-4 bg-bg-light">
            <div className="flex items-center justify-between mb-2">
                <div>
                    <h3 className="mb-0">Active deployment</h3>
                    <p className="text-muted text-sm mb-0">
                        Workers polling this queue execute new triggers. Old versions drain in the background.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={triggerGreeting}
                    disabledReason={activeDeployment ? undefined : 'No active deployment'}
                >
                    Trigger greeting
                </LemonButton>
            </div>
            {activeDeployment ? (
                <div className="grid grid-cols-4 gap-4">
                    <Field label="Code version" value={<code>{activeDeployment.code_version}</code>} />
                    <Field label="Image" value={<code className="break-all">{activeDeployment.image_name}</code>} />
                    <Field label="Task queue" value={<code>{activeDeployment.task_queue}</code>} />
                    <Field label="Active for" value={dayjs(activeDeployment.started_at).fromNow(true)} />
                </div>
            ) : (
                <div className="text-muted">
                    {activeDeploymentLoading
                        ? 'Loading…'
                        : 'No active deployment. Run ./bin/deploy-orchestra to ship one.'}
                </div>
            )}
            {deployments.length > 1 && (
                <div className="mt-3 text-sm text-muted">
                    {deployments.filter((d) => d.status === 'draining').length} previous version(s) draining.
                </div>
            )}
        </div>
    )
}

function Field({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
    return (
        <div>
            <div className="text-xs uppercase text-muted">{label}</div>
            <div className="text-sm">{value}</div>
        </div>
    )
}

function DeploymentsTable(): JSX.Element {
    const { deployments, deploymentsLoading } = useValues(orchestraLogic)

    const columns: LemonTableColumns<OrchestraDeployment> = [
        {
            title: 'Code version',
            dataIndex: 'code_version',
            render: (_, record) => <code>{record.code_version}</code>,
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: (_, record) => <DeploymentStatusTag status={record.status} />,
        },
        {
            title: 'Task queue',
            dataIndex: 'task_queue',
            render: (_, record) => <code>{record.task_queue}</code>,
        },
        {
            title: 'Started',
            dataIndex: 'started_at',
            render: (_, record) => dayjs(record.started_at).fromNow(),
        },
        {
            title: 'Finished',
            dataIndex: 'finished_at',
            render: (_, record) => (record.finished_at ? dayjs(record.finished_at).fromNow() : '—'),
        },
    ]

    return (
        <div className="mb-6">
            <h3 className="mb-2">Recent deployments</h3>
            <LemonTable
                columns={columns}
                dataSource={deployments}
                loading={deploymentsLoading}
                emptyState="No deployments yet."
                size="small"
            />
        </div>
    )
}

function OrchestraScene(): JSX.Element {
    const { executions, executionsLoading, statusFilter } = useValues(orchestraLogic)
    const { loadExecutions, setStatusFilter } = useActions(orchestraLogic)

    const columns: LemonTableColumns<OrchestraExecution> = [
        {
            title: 'Execution ID',
            dataIndex: 'execution_id',
            render: (_, record) => <Link to={urls.orchestraExecution(record.execution_id)}>{record.execution_id}</Link>,
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
            <ActiveDeploymentCard />
            <DeploymentsTable />
            <h3 className="mb-2">Executions</h3>
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
