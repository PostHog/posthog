import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonDialog, LemonDivider, LemonInput, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { MailHog } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { NewWorkflowModal } from './NewWorkflowModal'
import { getHogFlowStep } from './hogflows/steps/HogFlowSteps'
import { HogFlow } from './hogflows/types'
import { newWorkflowLogic } from './newWorkflowLogic'
import { workflowsLogic } from './workflowsLogic'

function WorkflowTypeTag({ workflow }: { workflow: HogFlow }): JSX.Element {
    const hasMessagingAction = useMemo(() => {
        return workflow.actions.some((action) => {
            return ['function_email', 'function_sms', 'function_slack'].includes(action.type)
        })
    }, [workflow.actions])

    if (hasMessagingAction) {
        return <LemonTag type="completion">Messaging</LemonTag>
    }
    return <LemonTag type="default">Automation</LemonTag>
}

function WorkflowActionsSummary({ workflow }: { workflow: HogFlow }): JSX.Element {
    const actionsByType = useMemo(() => {
        return workflow.actions.reduce(
            (acc, action) => {
                const step = getHogFlowStep(action, {})
                if (!step || !step.type.startsWith('function')) {
                    return acc
                }
                const key = 'template_id' in action.config ? action.config.template_id : action.type
                acc[key] = {
                    count: (acc[key]?.count || 0) + 1,
                    icon: step.icon,
                    color: step.color,
                }
                return acc
            },
            {} as Record<
                string,
                {
                    count: number
                    icon: JSX.Element
                    color: string
                }
            >
        )
    }, [workflow.actions])

    return (
        <Link to={urls.workflow(workflow.id, 'workflow')}>
            <div className="flex flex-row gap-2 items-center">
                {Object.entries(actionsByType).map(([type, { count, icon, color }]) => (
                    <div
                        key={type}
                        className="rounded px-1 flex items-center justify-center gap-1"
                        style={{
                            backgroundColor: `${color}20`,
                            color,
                        }}
                    >
                        {icon} {count}
                    </div>
                ))}
            </div>
        </Link>
    )
}

export function WorkflowsTable(): JSX.Element {
    useMountedLogic(workflowsLogic)
    const { filteredWorkflows, workflowsLoading, filters } = useValues(workflowsLogic)
    const { toggleWorkflowStatus, duplicateWorkflow, deleteWorkflow, setSearchTerm, setCreatedBy, setStatus } =
        useActions(workflowsLogic)
    const { showNewWorkflowModal } = useActions(newWorkflowLogic)

    const columns: LemonTableColumns<HogFlow> = [
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
            render: (_, item) => {
                return (
                    <LemonTableLink
                        to={urls.workflow(item.id, 'workflow')}
                        title={item.name}
                        description={item.description}
                    />
                )
            },
        },

        {
            title: 'Type',
            width: 0,
            render: (_, item) => {
                return <WorkflowTypeTag workflow={item} />
            },
        },

        {
            title: 'Trigger',
            width: 0,
            render: (_, item) => {
                return (
                    <Link to={urls.workflow(item.id, 'workflow') + '?node=trigger_node'}>
                        <LemonTag type="default">{capitalizeFirstLetter(item.trigger?.type ?? 'unknown')}</LemonTag>
                    </Link>
                )
            },
        },
        {
            title: 'Dispatches',
            width: 0,
            render: (_, item) => {
                return <WorkflowActionsSummary workflow={item} />
            },
        },
        {
            title: 'Created by',
            width: 0,
            render: (_, item) => {
                if (!item.created_by) {
                    return <span className="text-muted">Unknown</span>
                }
                return (
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={item.created_by} size="sm" />
                        <span>{item.created_by.first_name || item.created_by.email}</span>
                    </div>
                )
            },
        },
        {
            ...(updatedAtColumn() as LemonTableColumn<HogFlow, any>),
            width: 0,
        },
        {
            title: 'Last 7 days',
            width: 0,
            render: (_, { id }) => {
                return (
                    <Link to={urls.workflow(id, 'metrics')}>
                        <AppMetricsSparkline
                            logicKey={id}
                            forceParams={{
                                appSource: 'hog_flow',
                                appSourceId: id,
                                metricKind: ['success', 'failure'],
                                breakdownBy: 'metric_kind',
                                interval: 'day',
                                dateFrom: '-7d',
                            }}
                        />
                    </Link>
                )
            },
        },

        {
            title: 'Status',
            width: 0,
            key: 'status',
            sorter: (a, b) => a.status.localeCompare(b.status),
            render: (_, item) => {
                return (
                    <LemonTag type={item.status === 'active' ? 'success' : 'default'}>
                        {capitalizeFirstLetter(item.status)}
                    </LemonTag>
                )
            },
        },
        {
            width: 0,
            render: function Render(_, workflow: HogFlow) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    data-attr="workflow-edit"
                                    fullWidth
                                    status={workflow.status === 'draft' ? 'default' : 'danger'}
                                    onClick={() => toggleWorkflowStatus(workflow)}
                                    tooltip={
                                        workflow.status === 'draft'
                                            ? 'Enables the workflow to start sending messages'
                                            : 'Disables the workflow from sending any new messages. In-progress workflows will end immediately.'
                                    }
                                >
                                    {workflow.status === 'draft' ? 'Enable' : 'Disable'}
                                </LemonButton>
                                <LemonButton
                                    data-attr="workflow-duplicate"
                                    fullWidth
                                    onClick={() => duplicateWorkflow(workflow)}
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    data-attr="workflow-delete"
                                    fullWidth
                                    status="danger"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete workflow',
                                            description: (
                                                <p>
                                                    Are you sure you want to delete the workflow "
                                                    <strong>{workflow.name}</strong>"? This action cannot be undone.
                                                    In-progress workflows will end immediately.
                                                </p>
                                            ),
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => {
                                                    deleteWorkflow(workflow)
                                                },
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    const showProductIntroduction =
        !workflowsLoading && filteredWorkflows.length === 0 && !filters.search && !filters.createdBy && !filters.status

    return (
        <div className="workflows-section" data-attr="workflows-table" data-loading={workflowsLoading}>
            {showProductIntroduction && (
                <ProductIntroduction
                    productName="Workflow"
                    thingName="workflow"
                    description="Create workflows that automate actions or send messages to your users."
                    docsURL="https://posthog.com/docs/workflows/start-here"
                    action={() => {
                        showNewWorkflowModal()
                    }}
                    customHog={MailHog}
                    isEmpty
                />
            )}
            {!showProductIntroduction && (
                <div className="flex justify-between gap-2 flex-wrap mb-4">
                    <LemonInput
                        type="search"
                        placeholder="Search for workflows"
                        onChange={setSearchTerm}
                        value={filters.search}
                    />
                    <div className="flex items-center gap-2 flex-wrap">
                        <div className="flex items-center gap-2">
                            <span>Status:</span>
                            <LemonSelect
                                value={filters.status || 'all'}
                                onChange={(value) => setStatus(value === 'all' ? null : value)}
                                options={[
                                    { value: 'all', label: 'All statuses' },
                                    { value: 'active', label: 'Active' },
                                    { value: 'draft', label: 'Draft' },
                                    { value: 'archived', label: 'Archived' },
                                ]}
                                size="small"
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <span>Created by:</span>
                            <MemberSelect
                                value={filters.createdBy}
                                onChange={(user) => setCreatedBy(user?.uuid || null)}
                            />
                        </div>
                    </div>
                </div>
            )}
            <LemonTable
                dataSource={filteredWorkflows}
                loading={workflowsLoading}
                columns={columns}
                defaultSorting={{ columnKey: 'status', order: 1 }}
            />
            <NewWorkflowModal />
        </div>
    )
}
