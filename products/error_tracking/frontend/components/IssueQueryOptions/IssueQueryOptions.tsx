import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { issuesDataNodeLogic } from '../../logics/issuesDataNodeLogic'
import { ORDER_BY_OPTIONS, issueQueryOptionsLogic } from './issueQueryOptionsLogic'

/** Reload control shared across error tracking surfaces — spinner while loading, refresh icon otherwise. */
export const ReloadButton = ({
    loading,
    onClick,
    type = 'tertiary',
    children,
    tooltip,
}: {
    loading: boolean
    onClick: () => void
    type?: 'secondary' | 'tertiary'
    children?: ReactNode
    tooltip?: string
}): JSX.Element => (
    <LemonButton
        type={type}
        size="small"
        onClick={onClick}
        icon={loading ? <Spinner textColored /> : <IconRefresh />}
        tooltip={tooltip}
    >
        {children}
    </LemonButton>
)

/** Legacy sort + reload controls, used by the pre-redesign issues list. */
export const IssueQueryOptions = (): JSX.Element => {
    const { orderBy, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <span className="flex items-center justify-between gap-2 self-end">
            <Reload />
            <div className="flex items-center gap-2 self-end">
                <div className="flex items-center gap-1">
                    <span>Sort by:</span>

                    <LemonMenu
                        items={[
                            {
                                label: ORDER_BY_OPTIONS['last_seen'],
                                onClick: () => setOrderBy('last_seen'),
                            },
                            {
                                label: ORDER_BY_OPTIONS['first_seen'],
                                onClick: () => setOrderBy('first_seen'),
                            },
                            {
                                label: ORDER_BY_OPTIONS['occurrences'],
                                onClick: () => setOrderBy('occurrences'),
                            },
                            {
                                label: ORDER_BY_OPTIONS['users'],
                                onClick: () => setOrderBy('users'),
                            },
                            {
                                label: ORDER_BY_OPTIONS['sessions'],
                                onClick: () => setOrderBy('sessions'),
                            },
                        ]}
                    >
                        <LemonButton size="small" type="secondary">
                            {ORDER_BY_OPTIONS[orderBy]}
                        </LemonButton>
                    </LemonMenu>

                    <LemonSelect
                        onChange={setOrderDirection}
                        value={orderDirection}
                        options={[
                            {
                                value: 'DESC',
                                label: 'Descending',
                            },
                            {
                                value: 'ASC',
                                label: 'Ascending',
                            },
                        ]}
                        size="small"
                    />
                </div>
            </div>
        </span>
    )
}

const Reload = (): JSX.Element => {
    const { responseLoading } = useValues(issuesDataNodeLogic)
    const { reloadData, cancelQuery } = useActions(issuesDataNodeLogic)

    return (
        <ReloadButton
            type="secondary"
            loading={responseLoading}
            onClick={() => (responseLoading ? cancelQuery() : reloadData())}
        >
            {responseLoading ? 'Cancel' : 'Reload'}
        </ReloadButton>
    )
}

export const IssueReloadButton = (): JSX.Element => {
    const { responseLoading } = useValues(issuesDataNodeLogic)
    const { reloadData, cancelQuery } = useActions(issuesDataNodeLogic)

    return (
        <ReloadButton
            loading={responseLoading}
            onClick={() => (responseLoading ? cancelQuery() : reloadData())}
            tooltip={responseLoading ? 'Cancel' : 'Reload'}
        />
    )
}
