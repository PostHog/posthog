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

import { EndpointType } from '~/types'

import { endpointLogic } from './endpointLogic'
import { endpointsLogic } from './endpointsLogic'

interface EndpointsProps {
    tabId: string
}

interface EndpointsTableProps {
    tabId: string
}

export function Endpoints({ tabId }: EndpointsProps): JSX.Element {
    return (
        <>
            <EndpointsTable tabId={tabId} />
        </>
    )
}

export const EndpointsTable = ({ tabId }: EndpointsTableProps): JSX.Element => {
    const { setFilters } = useActions(endpointsLogic({ tabId }))
    const { endpoints, allEndpointsLoading, filters } = useValues(endpointsLogic({ tabId }))

    const { deleteEndpoint, deactivateEndpoint } = useActions(endpointLogic({ tabId }))

    const columns: LemonTableColumns<EndpointType> = [
        {
            title: 'Name',
            key: 'name',
            dataIndex: 'name',
            width: '25%',
            render: function Render(_, record) {
                return (
                    <LemonTableLink
                        // TODO: Add link to endpoint modal
                        // to={urls.endpointsEndpoint(record.name)}
                        title={record.name}
                        description={record.description}
                    />
                )
            },
            sorter: (a: EndpointType, b: EndpointType) => a.name.localeCompare(b.name),
        },
        createdAtColumn<EndpointType>() as LemonTableColumn<EndpointType, keyof EndpointType | undefined>,
        createdByColumn<EndpointType>() as LemonTableColumn<EndpointType, keyof EndpointType | undefined>,
        atColumn<EndpointType>('last_executed_at', 'Last executed at') as LemonTableColumn<
            EndpointType,
            keyof EndpointType | undefined
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
            sorter: (a: EndpointType, b: EndpointType) => Number(b.is_active) - Number(a.is_active),
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
                                    router.actions.push(urls.endpointsUsage({ requestNameFilter: [record.name] }))
                                }}
                                fullWidth
                            >
                                View usage
                            </LemonButton>

                            <LemonDivider />
                            <LemonButton
                                onClick={() => {
                                    deactivateEndpoint(record.name)
                                }}
                                fullWidth
                                status="alt"
                            >
                                Deactivate endpoint
                            </LemonButton>
                            <LemonButton
                                onClick={() => {
                                    deleteEndpoint(record.name)
                                }}
                                fullWidth
                                status="danger"
                            >
                                Delete endpoint
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
                    placeholder="Search for endpoints"
                    onChange={(x) => setFilters({ search: x })}
                    value={filters.search}
                />
            </div>
            <LemonTable
                data-attr="endpoints-table"
                pagination={{ pageSize: 20 }}
                dataSource={endpoints as EndpointType[]}
                rowKey="id"
                rowClassName={(record) => (record._highlight ? 'highlighted' : null)}
                columns={columns}
                loading={allEndpointsLoading}
                defaultSorting={{
                    columnKey: 'last_executed_at',
                    order: -1,
                }}
                emptyState="No endpoints matching your filters!"
                nouns={['endpoint', 'endpoints']}
            />
        </>
    )
}
