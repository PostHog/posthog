import { useActions, useValues } from 'kea'

import {
    Button,
    SelectTriggerIcon,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { QuillAssigneeIconDisplay } from '../../../components/Assignee/QuillAssigneeIconDisplay'
import { QuillAssigneeLabelDisplay } from '../../../components/Assignee/QuillAssigneeLabelDisplay'
import { QuillAssigneeSelect } from '../../../components/Assignee/QuillAssigneeSelect'
import { CodeOwnerOwnerMapping } from './codeownersImport'
import { codeOwnersModalLogic } from './codeOwnersModalLogic'

function OwnerPaths({ row }: { row: CodeOwnerOwnerMapping }): JSX.Element {
    const hasUsablePath = row.matchFragments.length > 0

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Text
                        size="xs"
                        variant={hasUsablePath ? 'muted' : 'default'}
                        className={hasUsablePath ? 'm-0 w-fit' : 'm-0 w-fit text-warning-foreground'}
                        render={<span tabIndex={0} />}
                    />
                }
            >
                {hasUsablePath
                    ? `${row.matchFragments.length} ${row.matchFragments.length === 1 ? 'path' : 'paths'}`
                    : 'no usable path'}
            </TooltipTrigger>
            <TooltipContent side="left">
                <div className="flex flex-col">
                    {row.patterns.map((pattern) => (
                        <span key={pattern}>{pattern}</span>
                    ))}
                </div>
            </TooltipContent>
        </Tooltip>
    )
}

export function QuillCodeOwnersConfigureTable(): JSX.Element {
    const { mappingRows } = useValues(codeOwnersModalLogic)
    const { setOwnerAssignee } = useActions(codeOwnersModalLogic)

    return (
        <Table>
            <TableHeader>
                <TableRow>
                    <TableHead>Owner</TableHead>
                    <TableHead className="text-right">PostHog role / user</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {mappingRows.map((row: CodeOwnerOwnerMapping) => (
                    <TableRow key={row.owner}>
                        <TableCell>
                            <div className="flex flex-col gap-1">
                                <Text size="xs" className="m-0 font-mono whitespace-nowrap" render={<span />}>
                                    {row.owner}
                                </Text>
                                <OwnerPaths row={row} />
                            </div>
                        </TableCell>
                        <TableCell>
                            <div className="flex justify-end">
                                <QuillAssigneeSelect
                                    assignee={row.assignee}
                                    onChange={(assignee) => setOwnerAssignee(row.owner, assignee)}
                                >
                                    {(assignee) => (
                                        <Button variant="outline" left className="w-64 max-w-full">
                                            <QuillAssigneeIconDisplay assignee={assignee} size="small" />
                                            <QuillAssigneeLabelDisplay
                                                assignee={assignee}
                                                className="min-w-0 truncate"
                                                placeholder="Assign…"
                                            />
                                            <SelectTriggerIcon className="ml-auto" />
                                        </Button>
                                    )}
                                </QuillAssigneeSelect>
                            </div>
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    )
}
