import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import type { EndpointVersionType } from '~/types'

import { endpointLogic } from '../endpointLogic'
import { EndpointTab, endpointSceneLogic } from '../endpointSceneLogic'

interface EndpointVersionsProps {
    tabId: string
}

function getStatusTagType(status: string | undefined): 'success' | 'danger' | 'warning' | 'default' {
    if (!status) {
        return 'warning'
    }
    switch (status.toLowerCase()) {
        case 'failed':
            return 'danger'
        case 'running':
            return 'warning'
        case 'completed':
            return 'success'
        default:
            return 'default'
    }
}

export function EndpointVersions({ tabId }: EndpointVersionsProps): JSX.Element {
    const { endpoint, versions, versionsLoading } = useValues(endpointLogic({ tabId }))
    const { updateEndpoint } = useActions(endpointLogic({ tabId }))
    const { viewingVersion } = useValues(endpointSceneLogic({ tabId }))

    if (!endpoint) {
        return <></>
    }

    const columns: LemonTableColumns<EndpointVersionType> = [
        {
            title: 'Version',
            dataIndex: 'version',
            key: 'version',
            width: '25%',
            render: function Render(_, record) {
                const isViewing = viewingVersion?.version === record.version
                const isCurrent = record.version === endpoint.current_version
                const versionUrl = combineUrl(urls.endpoint(endpoint.name), {
                    tab: EndpointTab.VERSIONS,
                    ...(isCurrent ? {} : { version: record.version }),
                }).url
                return (
                    <LemonTableLink
                        to={versionUrl}
                        title={
                            <>
                                v{record.version}
                                {isCurrent && (
                                    <LemonTag type="completion" className="ml-2">
                                        Latest
                                    </LemonTag>
                                )}
                                {isViewing && !isCurrent && (
                                    <LemonTag type="highlight" className="ml-2">
                                        Viewing
                                    </LemonTag>
                                )}
                            </>
                        }
                        description={record.description}
                    />
                )
            },
        },
        {
            title: 'Status',
            dataIndex: 'is_active',
            key: 'status',
            align: 'center',
            render: function RenderStatus(_, record) {
                return record.is_active ? (
                    <LemonTag type="success">Active</LemonTag>
                ) : (
                    <LemonTag type="danger">Inactive</LemonTag>
                )
            },
        },
        {
            title: 'Materialized',
            dataIndex: 'is_materialized',
            key: 'materialization',
            render: function RenderMaterialization(_, record) {
                if (!record.is_materialized) {
                    return <span className="text-muted">-</span>
                }
                return (
                    <div className="flex items-center gap-2">
                        <LemonTag type={getStatusTagType(record.materialization?.status)}>
                            {record.materialization?.status || 'Unknown'}
                        </LemonTag>
                    </div>
                )
            },
        },
        createdAtColumn<EndpointVersionType>() as any,
        createdByColumn<EndpointVersionType>() as any,
        {
            key: 'actions',
            width: 0,
            render: function RenderActions(_, record) {
                const isCurrent = record.version === endpoint.current_version
                const versionUrl = combineUrl(urls.endpoint(endpoint.name), {
                    tab: EndpointTab.VERSIONS,
                    ...(isCurrent ? {} : { version: record.version }),
                }).url
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton fullWidth to={versionUrl}>
                                    View version
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    onClick={() =>
                                        updateEndpoint(
                                            endpoint.name,
                                            { is_active: !record.is_active },
                                            { version: record.version }
                                        )
                                    }
                                >
                                    {record.is_active ? 'Deactivate version' : 'Activate version'}
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneSection
            title="Endpoint versions"
            description="Updating an endpoint's query creates a new version. However, you can manage each endpoint version's configuration separately. You can also either deactivate a single version, or the entire endpoint."
        >
            <LemonTable
                data-attr="endpoint-versions-table"
                dataSource={versions || []}
                columns={columns}
                loading={versionsLoading}
                rowKey="id"
                emptyState="No versions found"
                nouns={['version', 'versions']}
            />
        </SceneSection>
    )
}
