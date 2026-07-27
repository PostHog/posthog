import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { Button, Spinner, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from 'lib/ui/quill'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../../components/Assignee/AssigneeSelect'
import { assigneeSelectLogic } from '../../../components/Assignee/assigneeSelectLogic'
import { buildImpactRows } from './codeownersImpact'
import { CodeOwnerOwnerMapping } from './codeownersImport'
import { codeOwnersModalLogic } from './codeOwnersModalLogic'
import { exceptionsUrl, issuesUrl } from './codeownersUrls'

function pathsTooltip(patterns: string[]): JSX.Element {
    return <span className="block whitespace-pre-line text-left">{patterns.join('\n')}</span>
}

export function CodeOwnersConfigureTable(): JSX.Element {
    const { mappingRows } = useValues(codeOwnersModalLogic)
    const { setOwnerAssignee } = useActions(codeOwnersModalLogic)

    return (
        <div className="flex flex-col gap-2">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="px-0">Owner</TableHead>
                        <TableHead className="px-0 text-right">PostHog role / user</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {mappingRows.map((row: CodeOwnerOwnerMapping) => {
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
                                            onChange={(assignee) => setOwnerAssignee(row.owner, assignee)}
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

    const impactRows = useMemo(
        () => buildImpactRows(savableRows, matchResults, resolveAssignee),
        [matchResults, resolveAssignee, savableRows]
    )

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
                                        window.open(issuesUrl(row.patterns, dateRange), '_blank', 'noopener')
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
