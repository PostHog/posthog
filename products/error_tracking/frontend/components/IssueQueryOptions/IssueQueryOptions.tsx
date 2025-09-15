import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { issuesDataNodeLogic } from '../../logics/issuesDataNodeLogic'
import { issueQueryOptionsLogic } from './issueQueryOptionsLogic'

export const IssueQueryOptions = (): JSX.Element => {
    const { orderBy, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <span className="flex items-center justify-between gap-2 self-end">
            <Reload />
            <div className="flex items-center gap-2 self-end">
                <div className="flex items-center gap-1">
                    <span>Sort by:</span>
                    <LemonSelect
                        onChange={setOrderBy}
                        value={orderBy}
                        options={[
                            {
                                value: 'last_seen',
                                label: 'Last seen',
                            },
                            {
                                value: 'first_seen',
                                label: 'First seen',
                            },
                            {
                                value: 'occurrences',
                                label: 'Occurrences',
                            },
                            {
                                value: 'users',
                                label: 'Users',
                            },
                            {
                                value: 'sessions',
                                label: 'Sessions',
                            },
                        ]}
                        size="small"
                    />
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
        <LemonButton
            type="secondary"
            size="small"
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    reloadData()
                }
            }}
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
        >
            {responseLoading ? 'Cancel' : 'Reload'}
        </LemonButton>
    )
}
