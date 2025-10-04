import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { QueryEndpointType } from '~/types'

import { queryEndpointLogic } from './queryEndpointLogic'
import { queryEndpointsLogic } from './queryEndpointsLogic'

interface QueryEndpointsProps {
    tabId: string
}

interface QueryEndpointsTableProps {
    tabId: string
}

export function QueryEndpoints({ tabId }: QueryEndpointsProps): JSX.Element {
    return (
        <>
            <QueryEndpointsTable tabId={tabId} />
        </>
    )
}

export const QueryEndpointsTable = ({ tabId }: QueryEndpointsTableProps): JSX.Element => {
    const { setFilters } = useActions(queryEndpointsLogic({ tabId }))
    const { queryEndpoints, allQueryEndpointsLoading, filters } = useValues(queryEndpointsLogic({ tabId }))

    const { deleteQueryEndpoint, deactivateQueryEndpoint } = useActions(queryEndpointLogic({ tabId }))

    const columns: LemonTableColumns<QueryEndpointType> = [
        {
            title: 'Name',
            key: 'name',
            dataIndex: 'name',
            width: '25%',
            render: function Render(_, record) {
                return (
                    <LemonTableLink
                        // TODO: Add link to endpoint modal
                        // to={urls.embeddedAnalyticsQueryEndpoint(record.name)}
                        title={record.name}
                        description={record.description}
                    />
                )
            },
            sorter: (a: QueryEndpointType, b: QueryEndpointType) => a.name.localeCompare(b.name),
        },
        createdAtColumn<QueryEndpointType>() as LemonTableColumn<
            QueryEndpointType,
            keyof QueryEndpointType | undefined
        >,
        createdByColumn<QueryEndpointType>() as LemonTableColumn<
            QueryEndpointType,
            keyof QueryEndpointType | undefined
        >,
        atColumn<QueryEndpointType>('last_executed_at', 'Last executed at') as LemonTableColumn<
            QueryEndpointType,
            keyof QueryEndpointType | undefined
        >,
        {
            title: 'Endpoint path',
            key: 'endpoint_path',
            dataIndex: 'endpoint_path',
            render: (_, record) => (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => {
                        navigator.clipboard.writeText(record.endpoint_path)
                        lemonToast.success('Endpoint URL copied to clipboard')
                    }}
                    className="font-mono text-xs"
                >
                    {record.endpoint_path}
                </LemonButton>
            ),
        },
        {
            title: 'Status',
            key: 'is_active',
            dataIndex: 'is_active',
            align: 'center',
            render: (_, record) => (
                <span>
                    {record.is_active ? (
                        <LemonTag type="success">Active</LemonTag>
                    ) : (
                        <LemonTag type="danger">Inactive</LemonTag>
                    )}
                </span>
            ),
            sorter: (a: QueryEndpointType, b: QueryEndpointType) => Number(b.is_active) - Number(a.is_active),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, record) => (
                <More
                    overlay={
                        <>
                            <LemonButton
                                onClick={() => {
                                    router.actions.push(
                                        urls.embeddedAnalyticsUsage({ requestNameFilter: [record.name] })
                                    )
                                }}
                                fullWidth
                            >
                                View usage
                            </LemonButton>

                            <LemonDivider />
                            <LemonButton
                                onClick={() => {
                                    deactivateQueryEndpoint(record.name)
                                }}
                                fullWidth
                                status="alt"
                            >
                                Deactivate query endpoint
                            </LemonButton>
                            <LemonButton
                                onClick={() => {
                                    deleteQueryEndpoint(record.name)
                                }}
                                fullWidth
                                status="danger"
                            >
                                Delete query endpoint
                            </LemonButton>
                        </>
                    }
                />
            ),
        },
    ]

    return (
        <>
            <div className="flex justify-between gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    className="w-1/3"
                    placeholder="Search for query endpoints"
                    onChange={(x) => setFilters({ search: x })}
                    value={filters.search}
                />
            </div>
            <LemonTable
                data-attr="query-endpoints-table"
                pagination={{ pageSize: 20 }}
                dataSource={queryEndpoints as QueryEndpointType[]}
                rowKey="id"
                rowClassName={(record) => (record._highlight ? 'highlighted' : null)}
                columns={columns}
                loading={allQueryEndpointsLoading}
                // TODO: defaultSorting & onSort
                emptyState="No query endpoints matching your filters!"
                nouns={['query endpoint', 'query endpoints']}
            />
        </>
    )
}
