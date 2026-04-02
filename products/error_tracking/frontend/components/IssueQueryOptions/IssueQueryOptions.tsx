import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { issuesDataNodeLogic } from '../../logics/issuesDataNodeLogic'
import { ORDER_BY_OPTIONS, issueQueryOptionsLogic } from './issueQueryOptionsLogic'

export const IssueQueryOptions = (): JSX.Element => {
    const { orderBy, orderDirection, useQueryV2 } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection, setUseQueryV2 } = useActions(issueQueryOptionsLogic)
    const hasQueryV2Flag = useFeatureFlag('ERROR_TRACKING_QUERY_V2')

    return (
        <span className="flex items-center justify-between gap-2 self-end">
            <Reload />
            <div className="flex items-center gap-2 self-end">
                {hasQueryV2Flag && (
                    <LemonSwitch
                        checked={useQueryV2}
                        onChange={setUseQueryV2}
                        label="v2 query"
                        size="small"
                        tooltip="Use ClickHouse postgres connector join instead of separate Postgres queries"
                    />
                )}
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
