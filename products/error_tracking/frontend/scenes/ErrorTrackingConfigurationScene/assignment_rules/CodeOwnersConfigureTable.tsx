import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { Button, Spinner, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { ErrorTrackingIssueAssignee, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../../components/Assignee/AssigneeSelect'
import { Assignee, assigneeSelectLogic } from '../../../components/Assignee/assigneeSelectLogic'
import { buildOwnerFilters, CodeOwnerRow, codeOwnersModalLogic } from './codeOwnersModalLogic'

function assigneeLabel(assignee: Assignee): string {
    if (!assignee) {
        return 'Assign…'
    }
    return assignee.type === 'role' ? assignee.role.name : assignee.user.first_name || assignee.user.email
}

function pathsTooltip(patterns: string[]): JSX.Element {
    return <span className="block whitespace-pre-line text-left">{patterns.join('\n')}</span>
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
                                        <AssigneeSelect
                                            assignee={row.assignee}
                                            onChange={(assignee) => setAssignee(row.owner, assignee)}
                                        >
                                            {(assignee, isOpen) => (
                                                <ButtonPrimitive
                                                    className="w-64"
                                                    data-state={isOpen ? 'open' : 'closed'}
                                                >
                                                    <div className="flex min-w-0 items-center">
                                                        <AssigneeIconDisplay assignee={assignee} size="small" />
                                                        <AssigneeLabelDisplay
                                                            assignee={assignee}
                                                            className="ml-1 min-w-0 truncate"
                                                            size="small"
                                                            placeholder="Assign…"
                                                        />
                                                    </div>
                                                    <MenuOpenIndicator className="ml-auto" />
                                                </ButtonPrimitive>
                                            )}
                                        </AssigneeSelect>
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
