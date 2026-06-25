import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    LemonButton,
    LemonCollapse,
    LemonInput,
    LemonModal,
    LemonTable,
    ProfilePicture,
    Spinner,
} from '@posthog/lemon-ui'

import { ListHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { HogFlowBatchJob, MessageAsset } from './hogflows/types'
import { workflowAssetsLogic } from './workflowAssetsLogic'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

function EmptyAssets(): JSX.Element {
    return (
        <div className="flex flex-col bg-surface-primary rounded px-4 py-8 items-center text-center mx-auto">
            <ListHog width="100" height="100" className="mb-4" />
            <h2 className="text-xl leading-tight">No emails sent yet</h2>
            <p className="text-sm text-balance text-tertiary">
                Every email this workflow sends is captured here, so you can see exactly what each person received.
            </p>
        </div>
    )
}

function AssetViewerModal({ workflowId, parentRunId, actionId }: AssetsTableProps): JSX.Element {
    const logic = workflowAssetsLogic({ id: workflowId, parentRunId, actionId })
    const { selectedAsset, contentUrl, pdfLoading } = useValues(logic)
    const { closeAsset, downloadPdf } = useActions(logic)

    return (
        <LemonModal
            isOpen={!!selectedAsset}
            onClose={closeAsset}
            width={720}
            title={selectedAsset?.subject || 'Email'}
            description={selectedAsset ? `Sent to ${selectedAsset.recipient}` : undefined}
            footer={
                selectedAsset ? (
                    <LemonButton
                        type="primary"
                        loading={pdfLoading}
                        disabledReason={pdfLoading ? 'Generating PDF…' : undefined}
                        onClick={() => downloadPdf(selectedAsset)}
                    >
                        Download PDF
                    </LemonButton>
                ) : undefined
            }
        >
            {selectedAsset ? (
                // sandbox with no allow-scripts: render the email HTML + images but neutralize any JS.
                <iframe
                    title="Rendered email"
                    sandbox=""
                    src={contentUrl(selectedAsset)}
                    className="w-full h-[60vh] bg-white rounded border"
                />
            ) : null}
        </LemonModal>
    )
}

interface AssetsTableProps {
    workflowId: string
    parentRunId?: string
    actionId?: string
}

function AssetsTable({ workflowId, parentRunId, actionId }: AssetsTableProps): JSX.Element {
    const logic = workflowAssetsLogic({ id: workflowId, parentRunId, actionId })
    const { assets, assetsLoading, search } = useValues(logic)
    const { setSearch, openAsset } = useActions(logic)
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
            <AssetViewerModal workflowId={workflowId} parentRunId={parentRunId} actionId={actionId} />
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

function WorkflowBatchAssets({ workflowId, actionId }: { workflowId: string; actionId?: string }): JSX.Element {
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
                content: <AssetsTable workflowId={workflowId} parentRunId={job.id} actionId={actionId} />,
            }))}
        />
    )
}

export function WorkflowAssets(props: WorkflowLogicProps): JSX.Element {
    const { workflow, workflowLoading } = useValues(workflowLogic(props))
    const { searchParams } = useValues(router)
    const workflowId = props.id ?? 'new'
    // Deep link from a step's metric: ?assetAction=<actionId> pre-filters to that email step.
    const actionId = (searchParams.assetAction as string | undefined) || undefined

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
                <WorkflowBatchAssets workflowId={workflowId} actionId={actionId} />
            ) : (
                <AssetsTable workflowId={workflowId} actionId={actionId} />
            )}
        </div>
    )
}
