import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import type { FacetFilter } from 'lib/components/FacetSearchBar/facetQuery'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { UserBasicType } from '~/types'

import { WorkflowStatusTag } from '../WorkflowStatusTag'
import { TemplateRowMenu } from './TemplateRowMenu'
import { HEALTH_TAGS, OPTIONAL_COLUMN_TITLES, OptionalColumn, TRIGGER_LABELS, TYPE_LABELS } from './workflowListLabels'
import { WorkflowListNameCell } from './WorkflowListNameCell'
import { WorkflowListRow, WorkflowRow, rowCreatedBy } from './workflowListRows'
import { WorkflowRowMenu } from './WorkflowRowMenu'
import { WorkflowSendsCell } from './WorkflowSendsCell'

type Column = LemonTableColumn<WorkflowListRow, keyof WorkflowListRow | undefined>

function lastSevenDaysLabel(row: WorkflowRow): string | null {
    const totals = row.workflow.last_7_days
    return totals ? `${totals.failed} failed · ${totals.succeeded} succeeded` : null
}

const TYPE_TAGS = { messaging: 'completion', automation: 'default', loop: 'highlight' } as const

const OPTIONAL_RENDERERS: Record<OptionalColumn, Column['render']> = {
    type: (_, row) => {
        if (row.kind !== 'workflow' || row.workflow.type === 'broadcast') {
            return null
        }
        const tag = <LemonTag type={TYPE_TAGS[row.workflow.type]}>{TYPE_LABELS[row.workflow.type]}</LemonTag>
        return row.workflow.type === 'loop' ? <Link to={urls.codeLoopLink(row.id)}>{tag}</Link> : tag
    },
    trigger: (_, row) =>
        row.kind === 'workflow' && row.workflow.trigger_type ? (
            <LemonTag type="default">{TRIGGER_LABELS[row.workflow.trigger_type] ?? row.workflow.trigger_type}</LemonTag>
        ) : null,
    owner: (_, row) =>
        row.kind === 'workflow' ? (
            <span className="whitespace-nowrap">{row.owners.map((owner) => `@${owner}`).join(', ')}</span>
        ) : null,
    created_by: (_, row) => {
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
    last_7_days: (_, row) =>
        row.kind === 'workflow' ? (
            <Link to={urls.workflow(row.id, 'metrics')} className="whitespace-nowrap">
                {lastSevenDaysLabel(row) ?? 'Unavailable'}
            </Link>
        ) : null,
    health: (_, row) => {
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
}

function optionalColumn(column: OptionalColumn): Column {
    return { title: OPTIONAL_COLUMN_TITLES[column], key: column, width: 0, render: OPTIONAL_RENDERERS[column] }
}

/** Name, the picked optional columns, Status, Sends, Updated and the row menu. */
export function buildWorkflowsListV2Columns(visibleColumns: OptionalColumn[], filters: FacetFilter[]): Column[] {
    return [
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => a.name.localeCompare(b.name),
            render: (_, row) => <WorkflowListNameCell row={row} />,
        },
        ...(visibleColumns.includes('type') ? [optionalColumn('type')] : []),
        {
            title: 'Status',
            key: 'status',
            width: 0,
            render: (_, row) => (row.kind === 'workflow' ? <WorkflowStatusTag status={row.workflow.status} /> : null),
        },
        {
            title: 'Sends',
            key: 'sends',
            // Takes the leftover width and lets the cell truncate, so Updated and the menu stay in view.
            className: 'w-full max-w-0',
            render: (_, row) => <WorkflowSendsCell row={row} filters={filters} />,
        },
        ...visibleColumns.filter((column) => column !== 'type').map(optionalColumn),
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
}
