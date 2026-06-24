import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useMemo } from 'react'

import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { Button, Spinner, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { ErrorTrackingIssueAssignee, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { AssigneeDisplay } from '../../../components/Assignee/AssigneeDisplay'
import { Assignee, assigneeSelectLogic } from '../../../components/Assignee/assigneeSelectLogic'
import { buildOwnerFilters, CodeOwnerRow, codeOwnersModalLogic } from './codeOwnersModalLogic'

function assigneeLabel(assignee: Assignee): string {
    if (!assignee) {
        return 'Assign…'
    }
    return assignee.type === 'role' ? assignee.role.name : assignee.user.first_name || assignee.user.email
}

function assigneeValue(assignee: ErrorTrackingIssueAssignee | null): string | null {
    return assignee ? `${assignee.type}:${assignee.id}` : null
}

function parseAssigneeValue(value: string | null): ErrorTrackingIssueAssignee | null {
    if (!value) {
        return null
    }
    const [type, id] = value.split(':')
    if (type !== 'role' && type !== 'user') {
        return null
    }
    return { type, id: type === 'user' ? Number(id) : id }
}

interface AssigneeOption {
    value: string
    assignee: NonNullable<Assignee>
}

function pathsTooltip(patterns: string[]): JSX.Element {
    return <span className="block whitespace-pre-line text-left">{patterns.join('\n')}</span>
}

function assigneeSelectOption(option: AssigneeOption): {
    value: string
    label: JSX.Element
    labelInMenu: JSX.Element
} {
    const label = <AssigneeDisplay assignee={option.assignee} size="small" />

    return {
        value: option.value,
        label,
        labelInMenu: label,
    }
}

function exceptionsUrl(patterns: string[], dateRange: string): string {
    const filters = buildOwnerFilters(patterns)
    return combineUrl(
        urls.activity(ActivityTab.ExploreEvents),
        {},
        {
            q: {
                kind: NodeKind.DataTableNode,
                full: true,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                    orderBy: ['timestamp DESC'],
                    event: '$exception',
                    after: dateRange,
                    properties: filters.values,
                    tags: { productKey: ProductKey.ERROR_TRACKING },
                },
                propertiesViaUrl: true,
                showPersistentColumnConfigurator: true,
            },
        }
    ).url
}

export function CodeOwnersConfigureTable(): JSX.Element {
    const { mappingRows } = useValues(codeOwnersModalLogic)
    const { setOwnerAssignee } = useActions(codeOwnersModalLogic)
    const { roles, meFirstMembers } = useValues(assigneeSelectLogic)

    const roleOptions: AssigneeOption[] = roles.map((role) => ({
        value: `role:${role.id}`,
        assignee: { id: role.id, type: 'role', role },
    }))
    const userOptions: AssigneeOption[] = meFirstMembers.map((member) => ({
        value: `user:${member.user.id}`,
        assignee: { id: member.user.id, type: 'user', user: member.user },
    }))
    const lemonSelectOptions = [
        { title: 'Roles', options: roleOptions.map(assigneeSelectOption) },
        { title: 'Users', options: userOptions.map(assigneeSelectOption) },
    ]

    const setAssignee = (owner: string, assignee: ErrorTrackingIssueAssignee | null): void =>
        setOwnerAssignee(owner, assignee)

    return (
        <div className="flex flex-col gap-2">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="px-0">GitHub handle</TableHead>
                        <TableHead className="px-0 text-right">PostHog role / user</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {mappingRows.map((row: CodeOwnerRow) => {
                        return (
                            <TableRow key={row.owner}>
                                <TableCell className="px-0">
                                    <div className="flex flex-col gap-1">
                                        <span className="font-mono text-xs whitespace-nowrap">{row.owner}</span>
                                        {row.matchFragments.length === 0 ? (
                                            <Tooltip title={pathsTooltip(row.patterns)} placement="left">
                                                <span className="w-fit self-start text-xs text-warning">
                                                    no usable path
                                                </span>
                                            </Tooltip>
                                        ) : (
                                            <Tooltip title={pathsTooltip(row.patterns)} placement="left">
                                                <span className="w-fit self-start text-xs text-secondary">
                                                    {row.matchFragments.length}{' '}
                                                    {row.matchFragments.length === 1 ? 'path' : 'paths'}
                                                </span>
                                            </Tooltip>
                                        )}
                                    </div>
                                </TableCell>
                                <TableCell className="px-0">
                                    <div className="flex justify-end">
                                        <LemonSelect
                                            className="w-64"
                                            value={assigneeValue(row.assignee)}
                                            onChange={(value) => setAssignee(row.owner, parseAssigneeValue(value))}
                                            options={lemonSelectOptions}
                                            placeholder="Assign…"
                                            allowClear
                                            dropdownMatchSelectWidth
                                        />
                                    </div>
                                    {row.source === 'saved' && (
                                        <span className="text-xs text-secondary">saved mapping</span>
                                    )}
                                </TableCell>
                            </TableRow>
                        )
                    })}
                </TableBody>
            </Table>
        </div>
    )
}

export function CodeOwnersImpactTable(): JSX.Element {
    const { savableRows, matchResults, matchResultsLoading, dateRange } = useValues(codeOwnersModalLogic)
    const { resolveAssignee } = useValues(assigneeSelectLogic)

    const impactRows = useMemo(() => {
        const groups = new Map<
            string,
            { label: string; exceptionCount: number; issueCount: number; patterns: string[] }
        >()

        for (const row of savableRows) {
            if (!row.assignee) {
                continue
            }
            const resolved = resolveAssignee(row.assignee)
            if (!resolved) {
                continue
            }

            const key = row.assignee.type === 'role' ? `role:${row.assignee.id}` : `user:${row.assignee.id}`
            const existing = groups.get(key) ?? {
                label: assigneeLabel(resolved),
                exceptionCount: 0,
                issueCount: 0,
                patterns: [],
            }
            const count = matchResults[row.owner]
            existing.exceptionCount += count?.exceptionCount ?? 0
            existing.issueCount += count?.issueCount ?? 0
            existing.patterns.push(...row.patterns)
            groups.set(key, existing)
        }

        return Array.from(groups.values())
    }, [matchResults, resolveAssignee, savableRows])

    return (
        <Table>
            <TableHeader>
                <TableRow>
                    <TableHead className="px-0 text-left">PostHog role / user</TableHead>
                    <TableHead className="px-0 text-left">Exceptions</TableHead>
                    <TableHead className="px-0 text-left">Issues</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {impactRows.map((row) => (
                    <TableRow key={row.label}>
                        <TableCell className="px-0 text-left">{row.label}</TableCell>
                        <TableCell className="px-0 text-left">
                            {matchResultsLoading ? (
                                <Spinner />
                            ) : (
                                <Button
                                    variant="link-muted"
                                    size="xs"
                                    className="justify-start text-left px-0"
                                    onClick={() =>
                                        window.open(exceptionsUrl(row.patterns, dateRange), '_blank', 'noopener')
                                    }
                                >
                                    {row.exceptionCount}
                                </Button>
                            )}
                        </TableCell>
                        <TableCell className="px-0 text-left">
                            {matchResultsLoading ? (
                                <Spinner />
                            ) : (
                                <Button
                                    variant="link-muted"
                                    size="xs"
                                    className="justify-start text-left px-0"
                                    onClick={() =>
                                        window.open(
                                            urls.errorTracking({
                                                filterGroup: buildOwnerFilters(row.patterns),
                                                dateRange: { date_from: dateRange, date_to: null },
                                            }),
                                            '_blank',
                                            'noopener'
                                        )
                                    }
                                >
                                    {row.issueCount}
                                </Button>
                            )}
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    )
}
