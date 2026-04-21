import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonCheckbox, LemonDivider, LemonInput, LemonSelect, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { MailHog } from 'lib/components/hedgehogs'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { WorkflowsSceneProps } from '../WorkflowsScene'
import { getHogFlowStep } from './hogflows/steps/HogFlowSteps'
import { HogFlow } from './hogflows/types'
import { newWorkflowLogic } from './newWorkflowLogic'
import { workflowLogic } from './workflowLogic'
import { WorkflowStatusFilter, workflowsLogic } from './workflowsLogic'

const STATUS_CONFIG: Record<string, { label: string; type: 'success' | 'default' | 'muted' }> = {
    active: { label: 'Active', type: 'success' },
    draft: { label: 'Draft', type: 'default' },
    archived: { label: 'Archived', type: 'muted' },
}

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

export function WorkflowsTable(props: WorkflowsSceneProps): JSX.Element {
    const logic = workflowsLogic()
    const {
        filteredWorkflows,
        workflowsLoading,
        workflows,
        hasLoadedWorkflows,
        filters,
        selectedArchivedWorkflowIds,
        allArchivedSelected,
        selectedArchivedCount,
    } = useValues(logic)
    const {
        loadWorkflows,
        toggleWorkflowStatus,
        duplicateWorkflow,
        archiveWorkflow,
        restoreWorkflow,
        deleteWorkflow,
        deleteSelectedWorkflows,
        setSearchTerm,
        setCreatedBy,
        setStatusFilter,
        toggleArchivedWorkflowSelection,
        selectAllArchivedWorkflows,
        clearArchivedWorkflowSelection,
    } = useActions(logic)
    const { showNewWorkflowModal } = useActions(newWorkflowLogic)

    useOnMountEffect(() => {
        // Tricky: unmount the new workflow logic when leaving the new workflow scene
        // We can't just reset state within the logic's unmount as that would trigger when switching tabs
        const newWorkflowLogic = workflowLogic.findMounted({
            id: 'new',
            tabId: props.tabId,
        })
        newWorkflowLogic?.unmount()

        // Since logic isn't getting unmounted when navigating away from this scene, we need to reload workflows
        // when the component re-mounts
        loadWorkflows()
    })

    const isArchived = filters.status === 'archived'

    const columns: LemonTableColumns<HogFlow> = [
        ...(isArchived
            ? [
                  {
                      title: (
                          <LemonCheckbox
                              checked={allArchivedSelected ? true : selectedArchivedCount > 0 ? 'indeterminate' : false}
                              onChange={(checked: boolean) =>
                                  checked
                                      ? selectAllArchivedWorkflows(filteredWorkflows.map((w) => w.id))
                                      : clearArchivedWorkflowSelection()
                              }
                          />
                      ),
                      width: 0,
                      render: (_: any, item: HogFlow) => (
                          <LemonCheckbox
                              checked={selectedArchivedWorkflowIds.has(item.id)}
                              onChange={() => toggleArchivedWorkflowSelection(item.id)}
                          />
                      ),
                  },
              ]
            : []),
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
            render: (_, item) => {
                return item.status === 'archived' ? (
                    <Tooltip title="Restore this workflow to make changes">
                        <span className="font-semibold text-sm text-muted">{item.name}</span>
                    </Tooltip>
                ) : (
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
            render: (_, item) => {
                const config = STATUS_CONFIG[item.status] || STATUS_CONFIG.draft
                return <LemonTag type={config.type}>{config.label}</LemonTag>
            },
        },
        {
            width: 0,
            render: function Render(_, workflow: HogFlow) {
                return (
                    <More
                        overlay={
                            <>
                                {workflow.status !== 'archived' && (
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
                                )}
                                <LemonButton
                                    data-attr="workflow-duplicate"
                                    fullWidth
                                    onClick={() => duplicateWorkflow(workflow)}
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    data-attr="workflow-archive-restore"
                                    fullWidth
                                    status={workflow.status === 'archived' ? 'default' : 'danger'}
                                    onClick={() => {
                                        workflow.status === 'archived'
                                            ? restoreWorkflow(workflow)
                                            : archiveWorkflow(workflow)
                                    }}
                                >
                                    {workflow.status === 'archived' ? 'Restore' : 'Archive'}
                                </LemonButton>
                                {workflow.status === 'archived' && (
                                    <LemonButton
                                        data-attr="workflow-delete"
                                        fullWidth
                                        status="danger"
                                        onClick={() => deleteWorkflow(workflow)}
                                    >
                                        Delete
                                    </LemonButton>
                                )}
                            </>
                        }
                    />
                )
            },
        },
    ]

    const showProductIntroduction =
        hasLoadedWorkflows && !workflowsLoading && workflows.length === 0 && !filters.search && !filters.createdBy

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
                <>
                    <div className="flex justify-between gap-2 flex-wrap mb-4">
                        <LemonInput
                            type="search"
                            placeholder="Search for workflows"
                            onChange={setSearchTerm}
                            value={filters.search}
                        />
                        <div className="flex items-center gap-2">
                            <span>
                                <b>Status</b>
                            </span>
                            <LemonSelect
                                dropdownMatchSelectWidth={false}
                                size="small"
                                onChange={(value) => setStatusFilter(value as WorkflowStatusFilter)}
                                options={[
                                    { label: 'All', value: 'all' },
                                    { label: 'Active', value: 'active' },
                                    { label: 'Draft', value: 'draft' },
                                    { label: 'Archived', value: 'archived' },
                                ]}
                                value={filters.status}
                            />
                            <span className="ml-1">
                                <b>Created by</b>
                            </span>
                            <MemberSelect
                                value={filters.createdBy}
                                onChange={(user) => setCreatedBy(user?.uuid || null)}
                            />
                        </div>
                    </div>

                    {isArchived && selectedArchivedCount > 0 && (
                        <div className="flex items-center gap-2 mb-2">
                            <span className="text-muted text-sm">
                                {selectedArchivedCount} workflow{selectedArchivedCount !== 1 ? 's' : ''} selected
                            </span>
                            <LemonButton
                                type="secondary"
                                status="danger"
                                size="small"
                                onClick={deleteSelectedWorkflows}
                            >
                                Delete selected
                            </LemonButton>
                        </div>
                    )}

                    <LemonTable
                        dataSource={filteredWorkflows}
                        loading={workflowsLoading}
                        rowKey="id"
                        columns={columns}
                        defaultSorting={{ columnKey: 'updatedAt', order: 1 }}
                        pagination={{ pageSize: 30 }}
                        nouns={['workflow', 'workflows']}
                        emptyState="No workflows matching filters"
                    />
                </>
            )}
        </div>
    )
}
