import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { HedgehogGreek } from '@posthog/brand/hoggies'
import { LemonCollapse, LemonInput, LemonTable, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { EmailViewerModal } from './EmailViewerModal'
import { HogFlowBatchJob } from './hogflows/types'
import { MessageAsset } from './messageAssetsApi'
import { workflowAssetsLogic } from './workflowAssetsLogic'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

function EmptyAssets(): JSX.Element {
    return (
        <div className="flex flex-col bg-surface-primary rounded px-4 py-8 items-center text-center mx-auto">
            <HedgehogGreek width="100" height="100" className="mb-4" />
            <h2 className="text-xl leading-tight">No emails sent yet</h2>
            <p className="text-sm text-balance text-tertiary">
                Every email this workflow sends is captured here, so you can see exactly what each person received.
            </p>
        </div>
    )
}

function AssetViewerModal({ workflowId, parentRunId, actionId, invocationId }: AssetsTableProps): JSX.Element {
    const logic = workflowAssetsLogic({ id: workflowId, parentRunId, actionId, invocationId })
    const { selectedAsset } = useValues(logic)
    const { closeAsset } = useActions(logic)

    return (
        <EmailViewerModal
            workflowId={workflowId}
            invocationId={selectedAsset?.invocation_id ?? ''}
            actionId={selectedAsset?.action_id ?? ''}
            isOpen={!!selectedAsset}
            onClose={closeAsset}
            title={selectedAsset?.subject || 'Email'}
            description={selectedAsset ? `Sent to ${selectedAsset.recipient}` : undefined}
        />
    )
}

interface AssetsTableProps {
    workflowId: string
    parentRunId?: string
    actionId?: string
    invocationId?: string
}

function AssetsTable({ workflowId, parentRunId, actionId, invocationId }: AssetsTableProps): JSX.Element {
    const logic = workflowAssetsLogic({ id: workflowId, parentRunId, actionId, invocationId })
    const { assets, assetsLoading, search, selectedAsset } = useValues(logic)
    const { setSearch, openAsset } = useActions(logic)

    // Auto-open the asset when arriving via ?assetInvocation=<id>. Skip if one is
    // already open (user dismissed it) or the search box has focus.
    useEffect(() => {
        if (invocationId && assets.length === 1 && !selectedAsset && !search) {
            openAsset(assets[0])
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [invocationId, assets.length])
    const { workflow } = useValues(workflowLogic)

    const stepNameById = new Map(workflow.actions.map((action) => [action.id, action.name]))

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                placeholder="Search by recipient or subject"
                value={search}
                onChange={setSearch}
                className="max-w-100"
            />
            <LemonTable
                loading={assetsLoading}
                dataSource={assets}
                onRow={(asset: MessageAsset) => ({
                    onClick: () => openAsset(asset),
                    className: 'cursor-pointer',
                })}
                emptyState={<EmptyAssets />}
                columns={[
                    {
                        title: 'Recipient',
                        key: 'recipient',
                        render: (_, asset: MessageAsset) => (
                            <div className="flex items-center gap-2">
                                <ProfilePicture user={{ email: asset.recipient }} size="sm" />
                                <span>{asset.recipient}</span>
                            </div>
                        ),
                    },
                    {
                        title: 'Subject',
                        dataIndex: 'subject',
                        key: 'subject',
                    },
                    {
                        title: 'Step',
                        key: 'action_id',
                        render: (_, asset: MessageAsset) => stepNameById.get(asset.action_id) ?? '—',
                    },
                    {
                        title: 'Sent',
                        key: 'sent_at',
                        render: (_, asset: MessageAsset) => <TZLabel time={asset.sent_at} />,
                    },
                ]}
            />
            <AssetViewerModal
                workflowId={workflowId}
                parentRunId={parentRunId}
                actionId={actionId}
                invocationId={invocationId}
            />
        </div>
    )
}

function BatchJobAssetsHeader({ job }: { job: HogFlowBatchJob }): JSX.Element {
    return (
        <div className="flex gap-2 w-full justify-between">
            <strong>{job.id}</strong>
            <div className="flex items-center gap-2">
                <TZLabel title="Created at" time={job.created_at} />
                {job.created_by ? (
                    <ProfilePicture user={{ email: job.created_by.email || '' }} showName size="sm" />
                ) : (
                    <span className="text-muted text-sm">Scheduled run</span>
                )}
            </div>
        </div>
    )
}

function WorkflowBatchAssets({
    workflowId,
    actionId,
    invocationId,
}: {
    workflowId: string
    actionId?: string
    invocationId?: string
}): JSX.Element {
    const { jobs, batchWorkflowJobsLoading } = useValues(batchWorkflowJobsLogic({ id: workflowId }))

    if (batchWorkflowJobsLoading) {
        return (
            <div className="flex justify-center">
                <Spinner size="medium" />
            </div>
        )
    }

    if (!jobs.length) {
        return <EmptyAssets />
    }

    return (
        <LemonCollapse
            panels={jobs.map((job) => ({
                key: job.id,
                header: <BatchJobAssetsHeader job={job} />,
                content: (
                    <AssetsTable
                        workflowId={workflowId}
                        parentRunId={job.id}
                        actionId={actionId}
                        invocationId={invocationId}
                    />
                ),
            }))}
        />
    )
}

export function WorkflowAssets(props: WorkflowLogicProps): JSX.Element {
    const { workflow, workflowLoading } = useValues(workflowLogic(props))
    const { searchParams } = useValues(router)
    const workflowId = props.id ?? 'new'
    const actionId = (searchParams.assetAction as string | undefined) || undefined
    const invocationId = (searchParams.assetInvocation as string | undefined) || undefined

    if (workflowLoading) {
        return (
            <div className="flex justify-center">
                <Spinner size="medium" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2" data-attr="workflow-assets">
            {workflow?.trigger?.type === 'batch' ? (
                <WorkflowBatchAssets workflowId={workflowId} actionId={actionId} invocationId={invocationId} />
            ) : (
                <AssetsTable workflowId={workflowId} actionId={actionId} invocationId={invocationId} />
            )}
        </div>
    )
}
