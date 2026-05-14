import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
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
    const { openTriggerModal } = useActions(orchestraLogic)

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
                    onClick={openTriggerModal}
                    disabledReason={activeDeployment ? undefined : 'No active deployment'}
                >
                    Trigger execution
                </LemonButton>
            </div>
            {activeDeployment ? (
                <>
                    <div className="grid grid-cols-4 gap-4">
                        <Field label="Code version" value={<code>{activeDeployment.code_version}</code>} />
                        <Field label="Image" value={<code className="break-all">{activeDeployment.image_name}</code>} />
                        <Field label="Task queue" value={<code>{activeDeployment.task_queue}</code>} />
                        <Field label="Active for" value={dayjs(activeDeployment.started_at).fromNow(true)} />
                    </div>
                    <div className="mt-3">
                        <div className="text-xs uppercase text-muted mb-1">Registered executions</div>
                        {activeDeployment.registered_executions.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                                {activeDeployment.registered_executions.map((name) => (
                                    <LemonTag key={name}>
                                        <code>{name}</code>
                                    </LemonTag>
                                ))}
                            </div>
                        ) : (
                            <div className="text-muted text-sm">None reported by the deploy.</div>
                        )}
                    </div>
                </>
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

function TriggerExecutionModal(): JSX.Element {
    const { triggerModalOpen, executionsLoading, activeDeployment } = useValues(orchestraLogic)
    const { closeTriggerModal, triggerExecution } = useActions(orchestraLogic)
    const [executionType, setExecutionType] = useState('')
    const [inputJson, setInputJson] = useState('')

    const registered = activeDeployment?.registered_executions ?? []

    const submit = (): void => {
        if (!executionType.trim()) {
            return
        }
        triggerExecution(executionType.trim(), inputJson)
        setExecutionType('')
        setInputJson('')
    }

    return (
        <LemonModal
            width={520}
            title="Trigger execution"
            description="Starts a new execution against the active deployment's task queue."
            isOpen={triggerModalOpen}
            onClose={closeTriggerModal}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeTriggerModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submit}
                        loading={executionsLoading}
                        disabledReason={!executionType.trim() ? 'Pick an execution type' : null}
                    >
                        Trigger
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-y-3">
                <LemonField.Pure label="Execution type">
                    {registered.length > 0 ? (
                        <LemonSelect
                            value={executionType || null}
                            onChange={(value) => setExecutionType(value ?? '')}
                            placeholder="Pick a registered execution"
                            options={registered.map((name) => ({ value: name, label: name }))}
                            fullWidth
                        />
                    ) : (
                        <LemonInput
                            placeholder="greeting_execution"
                            autoFocus
                            value={executionType}
                            onChange={setExecutionType}
                        />
                    )}
                </LemonField.Pure>
                <LemonField.Pure label="Input (JSON, optional)">
                    <LemonTextArea
                        placeholder='{"name": "World", "age": 30}'
                        value={inputJson}
                        onChange={setInputJson}
                        minRows={4}
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}

function DeploymentsTable(): JSX.Element {
    const { deployments, deploymentsLoading, deploymentsLoadedOnce } = useValues(orchestraLogic)

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
        <SceneSection title="Deployment history">
            <LemonTable
                columns={columns}
                dataSource={deployments}
                loading={!deploymentsLoadedOnce && deploymentsLoading}
                emptyState="No deployments yet."
                pagination={{ pageSize: 10 }}
            />
        </SceneSection>
    )
}

function OrchestraScene(): JSX.Element {
    const { executions, executionsLoading, executionsLoadedOnce, statusFilter, executionDateRange } =
        useValues(orchestraLogic)
    const { setStatusFilter, setExecutionDateRange } = useActions(orchestraLogic)

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
        <SceneContent className="pb-8">
            <SceneTitleSection
                name="Orchestra"
                description="Durable, replayable code executions with versioned deployments"
                resourceType={{ type: 'orchestra' }}
            />
            <ActiveDeploymentCard />
            <TriggerExecutionModal />
            <DeploymentsTable />
            <SceneSection title="Executions">
                <div className="flex items-center gap-2">
                    <DateFilter
                        size="small"
                        dateFrom={executionDateRange.date_from}
                        dateTo={executionDateRange.date_to}
                        onChange={(date_from, date_to) => setExecutionDateRange(date_from ?? null, date_to ?? null)}
                    />
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
                </div>
                <LemonTable
                    columns={columns}
                    dataSource={executions}
                    loading={!executionsLoadedOnce && executionsLoading}
                    emptyState="No executions yet"
                    onRow={(record) => ({
                        onClick: () => {
                            window.location.href = urls.orchestraExecution(record.execution_id)
                        },
                    })}
                />
            </SceneSection>
        </SceneContent>
    )
}
