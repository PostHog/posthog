import { useActions, useValues } from 'kea'

import { IconSort, IconTriangleDown, IconTriangleUp } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import {
    ErrorTrackingQueryOrderBy,
    ORDER_BY_OPTIONS,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'

type ControlSize = 'xsmall' | 'small'

/** Sort field and direction in a single menu — one button, two sections. */
export const CombinedSortButton = ({ size = 'small' }: { size?: ControlSize }): JSX.Element => {
    const { orderBy, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <LemonMenu
            items={[
                {
                    title: 'Sort by',
                    items: Object.entries(ORDER_BY_OPTIONS).map(([value, label]) => ({
                        label,
                        active: orderBy === value,
                        onClick: () => setOrderBy(value as ErrorTrackingQueryOrderBy),
                    })),
                },
                {
                    title: 'Direction',
                    items: [
                        {
                            label: 'Newest first',
                            active: orderDirection === 'DESC',
                            onClick: () => setOrderDirection('DESC'),
                        },
                        {
                            label: 'Oldest first',
                            active: orderDirection === 'ASC',
                            onClick: () => setOrderDirection('ASC'),
                        },
                    ],
                },
            ]}
        >
            <LemonButton size={size} type="tertiary" icon={<IconSort />} tooltip="Sort">
                {ORDER_BY_OPTIONS[orderBy]}
            </LemonButton>
        </LemonMenu>
    )
}

/** Just the sort field — pairs with SortDirectionButton. */
export const SortFieldButton = ({ size = 'small' }: { size?: ControlSize }): JSX.Element => {
    const { orderBy } = useValues(issueQueryOptionsLogic)
    const { setOrderBy } = useActions(issueQueryOptionsLogic)

    return (
        <LemonMenu
            items={Object.entries(ORDER_BY_OPTIONS).map(([value, label]) => ({
                label,
                active: orderBy === value,
                onClick: () => setOrderBy(value as ErrorTrackingQueryOrderBy),
            }))}
        >
            <LemonButton size={size} type="tertiary" icon={<IconSort />} tooltip="Sort by">
                {ORDER_BY_OPTIONS[orderBy]}
            </LemonButton>
        </LemonMenu>
    )
}

/** One-click direction toggle — pairs with SortFieldButton. */
export const SortDirectionButton = ({ size = 'small' }: { size?: ControlSize }): JSX.Element => {
    const { orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <LemonButton
            size={size}
            type="tertiary"
            icon={orderDirection === 'DESC' ? <IconTriangleDown /> : <IconTriangleUp />}
            onClick={() => setOrderDirection(orderDirection === 'DESC' ? 'ASC' : 'DESC')}
            tooltip={
                orderDirection === 'DESC'
                    ? 'Newest first — click for oldest first'
                    : 'Oldest first — click for newest first'
            }
        />
    )
}
