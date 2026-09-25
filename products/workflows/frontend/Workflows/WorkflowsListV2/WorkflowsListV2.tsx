import { useActions, useValues } from 'kea'

import { IconDecisionTree, IconLetter, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonMenuOverlay, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FacetSearchBar } from 'lib/components/FacetSearchBar/FacetSearchBar'
import { TZLabel } from 'lib/components/TZLabel'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, UserBasicType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { WORKFLOW_TRIGGER_TYPE_OPTIONS } from '../workflowsLogic'
import { WorkflowStatusTag } from '../WorkflowStatusTag'
import { WorkflowListRow, WorkflowRow, rowCreatedBy } from './workflowListRows'
import { WorkflowSendsCell } from './WorkflowSendsCell'
import { OptionalColumn, workflowsListV2Logic } from './workflowsListV2Logic'

const PAGE_SIZE = 100

const TRIGGER_LABELS: Record<string, string> = Object.fromEntries(
    WORKFLOW_TRIGGER_TYPE_OPTIONS.map((option) => [option.value, option.label])
)

const HEALTH_TAGS: Record<WorkflowRow['health'], { label: string; type: 'danger' | 'success' | 'muted' }> = {
    failing: { label: 'Failing', type: 'danger' },
    healthy: { label: 'Healthy', type: 'success' },
    idle: { label: 'No runs', type: 'muted' },
}

function rowUrl(row: WorkflowListRow): string {
    return row.kind === 'workflow' ? urls.workflow(row.id, 'workflow') : urls.workflowsLibraryTemplate(row.id)
}

function lastSevenDaysLabel(row: WorkflowRow): string | null {
    const totals = row.workflow.last_7_days
    return totals ? `${totals.failed} failed · ${totals.succeeded} succeeded` : null
}

function NameCell({ row }: { row: WorkflowListRow }): JSX.Element {
    const description = row.kind === 'workflow' ? row.workflow.description : row.template.description
    const name = row.name || 'Untitled'
    return (
        <div className="flex items-center gap-2 min-w-0">
            {row.kind === 'workflow' ? (
                <IconDecisionTree className="shrink-0 text-secondary" />
            ) : (
                <IconLetter className="shrink-0 text-secondary" />
            )}
            {row.kind === 'workflow' && row.workflow.status === 'archived' ? (
                <Tooltip title="Restore this workflow to make changes">
                    <span data-attr="workflows-list-v2-name" className="font-semibold text-muted truncate">
                        {name}
                    </span>
                </Tooltip>
            ) : (
                <Tooltip title={description || undefined}>
                    <Link to={rowUrl(row)} data-attr="workflows-list-v2-name" className="font-semibold truncate">
                        {name}
                    </Link>
                </Tooltip>
            )}
        </div>
    )
}

function WorkflowRowMenu({ row }: { row: WorkflowRow }): JSX.Element {
    const { toggleWorkflowStatus, duplicateWorkflow, archiveWorkflow, restoreWorkflow, deleteWorkflow } =
        useActions(workflowsListV2Logic)
    const { status, user_access_level } = row.workflow
    return (
        <More
            overlay={
                <>
                    {status !== 'archived' && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={(user_access_level as AccessControlLevel | null) ?? undefined}
                        >
                            <LemonButton
                                data-attr="workflow-edit"
                                fullWidth
                                status={status === 'draft' ? 'default' : 'danger'}
                                onClick={() => toggleWorkflowStatus(row)}
                                tooltip={
                                    status === 'draft'
                                        ? 'Enables the workflow to start sending messages'
                                        : 'Disables the workflow from sending any new messages. In-progress workflows will end immediately.'
                                }
                            >
                                {status === 'draft' ? 'Enable' : 'Disable'}
                            </LemonButton>
                        </AccessControlAction>
                    )}
                    <LemonButton data-attr="workflow-duplicate" fullWidth onClick={() => duplicateWorkflow(row)}>
                        Duplicate
                    </LemonButton>
                    <LemonDivider />
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Workflow}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={(user_access_level as AccessControlLevel | null) ?? undefined}
                    >
                        <LemonButton
                            data-attr="workflow-archive-restore"
                            fullWidth
                            status={status === 'archived' ? 'default' : 'danger'}
                            onClick={() => (status === 'archived' ? restoreWorkflow(row) : archiveWorkflow(row))}
                        >
                            {status === 'archived' ? 'Restore' : 'Archive'}
                        </LemonButton>
                    </AccessControlAction>
                    {status === 'archived' && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={(user_access_level as AccessControlLevel | null) ?? undefined}
                        >
                            <LemonButton
                                data-attr="workflow-delete"
                                fullWidth
                                status="danger"
                                onClick={() => deleteWorkflow(row)}
                            >
                                Delete
                            </LemonButton>
                        </AccessControlAction>
                    )}
                </>
            }
        />
    )
}

function TemplateRowMenu({ row }: { row: Extract<WorkflowListRow, { kind: 'email_template' }> }): JSX.Element {
    const { duplicateTemplate, deleteTemplate } = useActions(workflowsListV2Logic)
    return (
        <More
            overlay={
                <LemonMenuOverlay
                    items={[
                        { label: 'Duplicate', onClick: () => duplicateTemplate(row) },
                        {
                            label: 'Delete',
                            status: 'danger' as const,
                            icon: <IconTrash />,
                            onClick: () => deleteTemplate(row),
                        },
                    ]}
                />
            }
        />
    )
}

function optionalColumns(): Record<
    OptionalColumn,
    LemonTableColumn<WorkflowListRow, keyof WorkflowListRow | undefined>
> {
    return {
        type: {
            title: 'Type',
            key: 'type',
            width: 0,
            render: (_, row) => {
                if (row.kind !== 'workflow') {
                    return null
                }
                if (row.workflow.type === 'loop') {
                    return (
                        <Link to={urls.codeLoopLink(row.id)}>
                            <LemonTag type="highlight">Loop</LemonTag>
                        </Link>
                    )
                }
                return row.workflow.type === 'messaging' ? (
                    <LemonTag type="completion">Messaging</LemonTag>
                ) : (
                    <LemonTag type="default">Automation</LemonTag>
                )
            },
        },
        trigger: {
            title: 'Trigger',
            key: 'trigger',
            width: 0,
            render: (_, row) =>
                row.kind === 'workflow' && row.workflow.trigger_type ? (
                    <LemonTag type="default">
                        {TRIGGER_LABELS[row.workflow.trigger_type] ?? row.workflow.trigger_type}
                    </LemonTag>
                ) : null,
        },
        owner: {
            title: 'Owner',
            key: 'owner',
            width: 0,
            render: (_, row) =>
                row.kind === 'workflow' ? (
                    <span className="whitespace-nowrap">{row.owners.map((owner) => `@${owner}`).join(', ')}</span>
                ) : null,
        },
        created_by: {
            title: 'Created by',
            key: 'created_by',
            width: 0,
            render: (_, row) => {
                const user = rowCreatedBy(row)
                if (!user) {
                    return <span className="text-muted">Unknown</span>
                }
                return (
                    <div className="flex items-center gap-2 whitespace-nowrap">
                        <ProfilePicture user={user as UserBasicType} size="sm" />
                        <span>{user.first_name || user.email}</span>
                    </div>
                )
            },
        },
        last_7_days: {
            title: 'Last 7 days',
            key: 'last_7_days',
            width: 0,
            render: (_, row) =>
                row.kind === 'workflow' ? (
                    <Link to={urls.workflow(row.id, 'metrics')} className="whitespace-nowrap">
                        {lastSevenDaysLabel(row) ?? 'Unavailable'}
                    </Link>
                ) : null,
        },
        health: {
            title: 'Health',
            key: 'health',
            width: 0,
            render: (_, row) => {
                if (row.kind !== 'workflow') {
                    return null
                }
                const tag = HEALTH_TAGS[row.health]
                const counts = lastSevenDaysLabel(row)
                return (
                    <Tooltip title={counts ? `${counts} in the last 7 days` : 'No runs in the last 7 days'}>
                        <LemonTag type={tag.type}>{tag.label}</LemonTag>
                    </Tooltip>
                )
            },
        },
    }
}

export function WorkflowsListV2(): JSX.Element {
    const { rows, filteredRows, facets, matchesText, value, listLoaded, listDataLoading, loadFailed, visibleColumns } =
        useValues(workflowsListV2Logic)
    const { setValue, loadList, clearFilters } = useActions(workflowsListV2Logic)

    useOnMountEffect(() => {
        // Leaving the new-workflow scene keeps its logic mounted, so drop it here as WorkflowsTable does.
        workflowLogic.findMounted({ id: 'new' })?.unmount()
    })

    const optional = optionalColumns()
    const columns: LemonTableColumn<WorkflowListRow, keyof WorkflowListRow | undefined>[] = [
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => a.name.localeCompare(b.name),
            render: (_, row) => <NameCell row={row} />,
        },
        ...(visibleColumns.includes('type') ? [optional.type] : []),
        {
            title: 'Status',
            key: 'status',
            width: 0,
            render: (_, row) => (row.kind === 'workflow' ? <WorkflowStatusTag status={row.workflow.status} /> : null),
        },
        {
            title: 'Sends',
            key: 'sends',
            className: 'max-w-120',
            render: (_, row) => <WorkflowSendsCell row={row} filters={value.filters} />,
        },
        ...visibleColumns.filter((column) => column !== 'type').map((column) => optional[column]),
        {
            title: 'Updated',
            key: 'updatedAt',
            dataIndex: 'updatedAt',
            width: 0,
            align: 'right',
            sorter: (a, b) => Date.parse(a.updatedAt) - Date.parse(b.updatedAt),
            render: (_, row) => (
                <div className="whitespace-nowrap text-right">
                    <TZLabel time={row.updatedAt} />
                </div>
            ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, row) =>
                row.kind === 'workflow' ? <WorkflowRowMenu row={row} /> : <TemplateRowMenu row={row} />,
        },
    ]

    const renderBody = (): JSX.Element => {
        if (loadFailed) {
            return (
                <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
                    <span className="font-semibold">Couldn't load workflows</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={listDataLoading}
                        onClick={loadList}
                        data-attr="workflows-list-v2-retry"
                    >
                        Retry
                    </LemonButton>
                </div>
            )
        }
        if (listLoaded && rows.length > 0 && filteredRows.length === 0) {
            return (
                <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
                    <span>No workflows or email templates match these filters</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={clearFilters}
                        data-attr="workflows-list-v2-clear-filters"
                    >
                        Clear filters
                    </LemonButton>
                </div>
            )
        }
        return (
            <LemonTable
                size="small"
                dataSource={filteredRows}
                loading={!listLoaded}
                rowKey={(row) => `${row.kind}-${row.id}`}
                columns={columns}
                pagination={{ pageSize: PAGE_SIZE }}
                nouns={['item', 'items']}
                emptyState="No workflows yet"
            />
        )
    }

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="workflows-list-v2">
            <FacetSearchBar
                facets={facets}
                items={rows}
                value={value}
                onChange={setValue}
                matchesText={matchesText}
                placeholder="Search workflows, or filter with status:, channel:, from: and more"
                dataAttr="workflows-search"
            />
            {renderBody()}
        </div>
    )
}
