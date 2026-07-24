import { useActions, useValues } from 'kea'

import { IconChevronDown, IconRefresh, IconSort } from '@posthog/icons'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Spinner,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'

import { issuesDataNodeLogic } from '../../logics/issuesDataNodeLogic'
import { ORDER_BY_OPTIONS, issueQueryOptionsLogic } from './issueQueryOptionsLogic'
import type { ErrorTrackingQueryOrderBy, ErrorTrackingQueryOrderDirection } from './issueQueryOptionsLogic'

export const IssueSortButton = (): JSX.Element => {
    const { orderBy, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="default"
                        aria-label={`Sort by ${ORDER_BY_OPTIONS[orderBy]}, ${orderDirection === 'DESC' ? 'descending' : 'ascending'}`}
                    >
                        <IconSort className={orderDirection === 'ASC' ? 'rotate-180' : undefined} />
                        {ORDER_BY_OPTIONS[orderBy]}
                        <IconChevronDown className="size-4" />
                    </Button>
                }
            />
            <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuRadioGroup
                    value={orderBy}
                    onValueChange={(value) => setOrderBy(value as ErrorTrackingQueryOrderBy)}
                >
                    <DropdownMenuLabel>Sort by</DropdownMenuLabel>
                    {Object.entries(ORDER_BY_OPTIONS).map(([value, label]) => (
                        <DropdownMenuRadioItem key={value} value={value} closeOnClick={false}>
                            {label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuRadioGroup
                    value={orderDirection}
                    onValueChange={(value) => setOrderDirection(value as ErrorTrackingQueryOrderDirection)}
                >
                    <DropdownMenuLabel>Direction</DropdownMenuLabel>
                    <DropdownMenuRadioItem value="DESC" closeOnClick={false}>
                        Descending
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="ASC" closeOnClick={false}>
                        Ascending
                    </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export const ReloadIssuesButton = (): JSX.Element => {
    const { responseLoading } = useValues(issuesDataNodeLogic)
    const { reloadData, cancelQuery } = useActions(issuesDataNodeLogic)

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon"
                        aria-label={responseLoading ? 'Cancel issue reload' : 'Reload issues'}
                        aria-busy={responseLoading}
                        onClick={() => {
                            if (responseLoading) {
                                cancelQuery()
                            } else {
                                reloadData()
                            }
                        }}
                    />
                }
            >
                {responseLoading ? <Spinner /> : <IconRefresh />}
            </TooltipTrigger>
            <TooltipContent>{responseLoading ? 'Cancel issue reload' : 'Reload issues'}</TooltipContent>
        </Tooltip>
    )
}
