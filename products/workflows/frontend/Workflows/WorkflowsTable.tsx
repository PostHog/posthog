import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonCheckbox, LemonInput, LemonSelect, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { MemberSelect } from 'lib/components/MemberSelect'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { HogFlow } from './hogflows/types'
import { WorkflowDispatch, WorkflowDispatchIcons } from './WorkflowDispatchIcons'
import { workflowLogic } from './workflowLogic'
import { WorkflowRowMenuOverlay } from './WorkflowRowMenuOverlay'
import { findMatchingWorkflowSteps } from './workflowSearchMatches'
import {
    WORKFLOW_TRIGGER_TYPE_OPTIONS,
    WorkflowStatusFilter,
    WorkflowTriggerTypeFilter,
    WorkflowTypeFilter,
    workflowsLogic,
} from './workflowsLogic'
import { WorkflowStatusTag } from './WorkflowStatusTag'
import { WorkflowStepMatches } from './WorkflowStepMatches'

function WorkflowTypeTag({ workflow }: { workflow: HogFlow }): JSX.Element {
    const hasMessagingAction = useMemo(() => {
        // Keep in sync with MESSAGING_ACTION_TYPES in products/workflows/backend/models/hog_flow/hog_flow.py,
        // which the list API's `type` filter uses - the tag and the filter must agree on what "Messaging" is.
        return workflow.actions.some((action) => {
            return ['function_email', 'function_sms', 'function_push'].includes(action.type)
        })
    }, [workflow.actions])

    if (workflow.origin_product === 'loops') {
        return (
            <Link to={urls.codeLoopLink(workflow.id)}>
                <LemonTag type="highlight">Loop</LemonTag>
            </Link>
        )
    }
    if (hasMessagingAction) {
        return <LemonTag type="completion">Messaging</LemonTag>
    }
    return <LemonTag type="default">Automation</LemonTag>
}

function WorkflowActionsSummary({ workflow }: { workflow: HogFlow }): JSX.Element {
    const dispatches = useMemo(() => {
        const byTemplate = new Map<string, WorkflowDispatch>()
        for (const action of workflow.actions) {
            if (!action.type.startsWith('function')) {
                continue
            }
            const templateId = 'template_id' in action.config ? action.config.template_id : action.type
            const existing = byTemplate.get(templateId)
            byTemplate.set(templateId, {
                actionType: existing?.actionType ?? action.type,
                templateId,
                count: (existing?.count ?? 0) + 1,
            })
        }
        return [...byTemplate.values()]
    }, [workflow.actions])

    return (
        <Link to={urls.workflow(workflow.id, 'workflow')}>
            <WorkflowDispatchIcons dispatches={dispatches} />
        </Link>
    )
}

export function WorkflowsTable(): JSX.Element {
    const logic = workflowsLogic()
    const {
        workflowsLoading,
        workflows,
        pagination,
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
        setFilters,
        toggleArchivedWorkflowSelection,
        selectAllArchivedWorkflows,
        clearArchivedWorkflowSelection,
    } = useActions(logic)

    useOnMountEffect(() => {
        // Tricky: unmount the new workflow logic when leaving the new workflow scene
        // We can't just reset state within the logic's unmount as that would trigger when switching tabs
        const newWorkflowLogic = workflowLogic.findMounted({
            id: 'new',
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
                                      ? selectAllArchivedWorkflows(workflows.results.map((w) => w.id))
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
                const stepMatches = findMatchingWorkflowSteps(item, filters.search)
                return (
                    <>
                        {item.status === 'archived' ? (
                            <Tooltip title="Restore this workflow to make changes">
                                <span className="font-semibold text-sm text-muted">{item.name}</span>
                            </Tooltip>
                        ) : (
                            <LemonTableLink
                                to={urls.workflow(item.id, 'workflow')}
                                title={item.name}
                                description={item.description}
                                truncateDescription
                            />
                        )}
                        {stepMatches.length > 0 && <WorkflowStepMatches workflow={item} matches={stepMatches} />}
                    </>
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
                            // Lines, not stacked bars: Started counts a run that also lands in
                            // Completed or Failed the same day, so a stacked total would double-count.
                            type="line"
                            metricLabels={{ triggered: 'Started', succeeded: 'Completed', failed: 'Failed' }}
                            // Same colors as the workflow metrics tab: triggered is blue there too.
                            metricColors={{ triggered: 'blue', succeeded: 'success', failed: 'danger' }}
                            forceParams={{
                                // The versioned mirror keys every run's metrics (including batch runs,
                                // which the plain hog_flow source keys under the batch job id) as
                                // `<flow id>/<version>`, so a prefix match covers all activity.
                                appSource: 'hog_flow_version',
                                appSourceIdPrefix: `${id}/`,
                                // Run-level rows carry an empty instance_id; per-action succeeded/failed
                                // rows carry the action id. Filter to run-level so Completed and Failed
                                // count runs, not steps. triggered is run-level too, so Started is unaffected.
                                instanceId: '',
                                metricName: ['triggered', 'succeeded', 'failed'],
                                breakdownBy: 'metric_name',
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
            render: (_, item) => <WorkflowStatusTag status={item.status} />,
        },
        {
            width: 0,
            render: function Render(_, workflow: HogFlow) {
                return (
                    <More
                        overlay={
                            <WorkflowRowMenuOverlay
                                status={workflow.status}
                                userAccessLevel={workflow.user_access_level}
                                onToggleStatus={() => toggleWorkflowStatus(workflow)}
                                onDuplicate={() => duplicateWorkflow(workflow)}
                                onArchive={() => archiveWorkflow(workflow)}
                                onRestore={() => restoreWorkflow(workflow)}
                                onDelete={() => deleteWorkflow(workflow)}
                            />
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="workflows-section" data-attr="workflows-table" data-loading={workflowsLoading}>
            <>
                <div className="flex justify-between gap-2 flex-wrap mb-4">
                    <LemonInput
                        type="search"
                        placeholder="Search for workflows"
                        onChange={(search) => setFilters({ search })}
                        value={filters.search}
                    />
                    <div className="flex items-center gap-2 flex-wrap">
                        <span>
                            <b>Status</b>
                        </span>
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            size="small"
                            onChange={(value) => setFilters({ status: value as WorkflowStatusFilter })}
                            options={[
                                { label: 'All', value: 'all' },
                                { label: 'Active', value: 'active' },
                                { label: 'Draft', value: 'draft' },
                                { label: 'Archived', value: 'archived' },
                            ]}
                            value={filters.status}
                        />
                        <span className="ml-1">
                            <b>Type</b>
                        </span>
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            size="small"
                            onChange={(value) => setFilters({ type: value as WorkflowTypeFilter })}
                            options={[
                                { label: 'All', value: 'all' },
                                { label: 'Messaging', value: 'messaging' },
                                { label: 'Automation', value: 'automation' },
                                { label: 'Loop', value: 'loop' },
                            ]}
                            value={filters.type}
                        />
                        <span className="ml-1">
                            <b>Trigger</b>
                        </span>
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            size="small"
                            onChange={(value) => setFilters({ triggerType: value as WorkflowTriggerTypeFilter })}
                            options={WORKFLOW_TRIGGER_TYPE_OPTIONS}
                            value={filters.triggerType}
                        />
                        <span className="ml-1">
                            <b>Created by</b>
                        </span>
                        <MemberSelect
                            value={filters.createdBy}
                            onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                        />
                    </div>
                </div>

                {isArchived && selectedArchivedCount > 0 && (
                    <div className="flex items-center gap-2 mb-2">
                        <span className="text-muted text-sm">
                            {selectedArchivedCount} workflow{selectedArchivedCount !== 1 ? 's' : ''} selected
                        </span>
                        <LemonButton type="secondary" status="danger" size="small" onClick={deleteSelectedWorkflows}>
                            Delete selected
                        </LemonButton>
                    </div>
                )}

                <LemonTable
                    dataSource={workflows.results}
                    loading={workflowsLoading}
                    rowKey="id"
                    columns={columns}
                    defaultSorting={{ columnKey: 'updatedAt', order: 1 }}
                    pagination={pagination}
                    nouns={['workflow', 'workflows']}
                    emptyState="No workflows matching filters"
                />
            </>
        </div>
    )
}
