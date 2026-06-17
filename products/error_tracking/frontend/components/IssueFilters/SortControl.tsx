import { useActions, useValues } from 'kea'

import { IconArrowRight, IconCheck, IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import {
    ErrorTrackingQueryOrderBy,
    ErrorTrackingQueryOrderDirection,
    ORDER_BY_OPTIONS,
    issueQueryOptionsLogic,
} from '../IssueQueryOptions/issueQueryOptionsLogic'

type Direction = ErrorTrackingQueryOrderDirection

const ORDER_ENTRIES = Object.entries(ORDER_BY_OPTIONS) as [ErrorTrackingQueryOrderBy, string][]

const opposite = (direction: Direction): Direction => (direction === 'DESC' ? 'ASC' : 'DESC')

const isTimeField = (orderBy: ErrorTrackingQueryOrderBy): boolean => orderBy === 'last_seen' || orderBy === 'first_seen'

/** Field-aware direction label — "Newest first" for time fields, "Highest first" for counts. */
const directionLabel = (orderBy: ErrorTrackingQueryOrderBy, direction: Direction): string => {
    if (isTimeField(orderBy)) {
        return direction === 'DESC' ? 'Newest first' : 'Oldest first'
    }
    return direction === 'DESC' ? 'Highest first' : 'Lowest first'
}

/** Single arrow that points down for DESC, up for ASC. */
const DirectionArrow = ({ direction }: { direction: Direction }): JSX.Element => (
    <IconArrowRight className={cn(direction === 'DESC' ? 'rotate-90' : '-rotate-90')} />
)

interface SortPopoverProps {
    orderBy: ErrorTrackingQueryOrderBy
    orderDirection: Direction
    setOrderBy: (orderBy: ErrorTrackingQueryOrderBy) => void
    setOrderDirection: (orderDirection: Direction) => void
}

const SortPopover = ({ orderBy, orderDirection, setOrderBy, setOrderDirection }: SortPopoverProps): JSX.Element => (
    <div className="flex flex-col gap-1 p-1 min-w-[210px]">
        <div className="px-2 pt-1 pb-0.5 text-xs font-medium text-secondary">Sort by</div>
        {ORDER_ENTRIES.map(([value, label]) => (
            <LemonButton
                key={value}
                size="small"
                fullWidth
                active={orderBy === value}
                sideIcon={orderBy === value ? <IconCheck /> : undefined}
                onClick={() => setOrderBy(value)}
            >
                {label}
            </LemonButton>
        ))}
        <LemonDivider className="my-1" />
        <div className="px-2 pb-0.5 text-xs font-medium text-secondary">Direction</div>
        <LemonButton
            size="small"
            fullWidth
            icon={<DirectionArrow direction={orderDirection} />}
            onClick={() => setOrderDirection(opposite(orderDirection))}
        >
            {directionLabel(orderBy, orderDirection)}
        </LemonButton>
    </div>
)

/** Sort summary control: direction arrow + field label + chevron, opening a
 *  popover with the field list and a direction toggle. Wired to the
 *  scene-bound issueQueryOptionsLogic. */
export const SortControl = (): JSX.Element => {
    const { orderBy, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <SortPopover
                    orderBy={orderBy}
                    orderDirection={orderDirection}
                    setOrderBy={setOrderBy}
                    setOrderDirection={setOrderDirection}
                />
            }
        >
            <LemonButton
                size="small"
                type="tertiary"
                icon={<DirectionArrow direction={orderDirection} />}
                sideIcon={<IconChevronDown />}
                tooltip="Sort issues"
            >
                {ORDER_BY_OPTIONS[orderBy]}
            </LemonButton>
        </LemonDropdown>
    )
}
