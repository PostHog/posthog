import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonDialog, LemonTable, type LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import type { EndpointMaterializationType, EndpointVersionType } from '~/types'

import { endpointLogic } from '../endpointLogic'
import { endpointSceneLogic } from '../endpointSceneLogic'

interface EndpointVersionsProps {
    tabId: string
}

function getMaterializationStatusDisplay(
    isMaterialized: boolean,
    materialization?: EndpointMaterializationType
): { label: string; type: 'success' | 'warning' | 'danger' | 'default' } {
    if (!isMaterialized) {
        return { label: 'Disabled', type: 'default' }
    }

    const status = materialization?.status?.toLowerCase()

    switch (status) {
        case 'completed':
            return {
                label: 'Active',
                type: 'success',
            }
        case 'running':
            return { label: 'Running', type: 'warning' }
        case 'pending':
            return { label: 'Pending', type: 'warning' }
        case 'failed':
            return { label: 'Failed', type: 'danger' }
        default:
            return { label: 'Unknown', type: 'default' }
    }
}

export function EndpointVersions({ tabId }: EndpointVersionsProps): JSX.Element {
    const { endpoint } = useValues(endpointLogic({ tabId }))
    const { versions, versionsLoading, viewingVersion } = useValues(endpointSceneLogic({ tabId }))
    const { selectVersion, updateVersionMaterialization } = useActions(endpointSceneLogic({ tabId }))
    const { confirmToggleActive } = useActions(endpointLogic({ tabId }))
    const sortedVersions = useMemo(() => [...versions].sort((a, b) => b.version - a.version), [versions])

    if (!endpoint) {
        return <></>
    }

    const handleToggleVersionActive = (item: EndpointVersionType, isLatest: boolean): void => {
        if (isLatest) {
            confirmToggleActive(endpoint)
            return
        }
        const isActivating = !item.is_active
        LemonDialog.open({
            title: isActivating ? 'Activate version?' : 'Deactivate version?',
            content: (
                <div className="text-sm text-secondary">
                    {isActivating
                        ? `Version ${item.version} will be accessible via the API.`
                        : `Version ${item.version} will no longer be accessible via the API.`}
                </div>
            ),
            primaryButton: {
                children: isActivating ? 'Activate' : 'Deactivate',
                type: 'primary',
                status: isActivating ? undefined : 'danger',
                onClick: () => updateVersionMaterialization(item.version, { is_active: isActivating }),
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const handleToggleMaterialization = (item: EndpointVersionType, isMaterialized: boolean): void => {
        const isEnabling = !isMaterialized
        LemonDialog.open({
            title: isEnabling ? 'Enable materialization?' : 'Disable materialization?',
            content: (
                <div className="text-sm text-secondary">
                    {isEnabling
                        ? `Version ${item.version} results will be pre-computed and cached.`
                        : `Version ${item.version} will run queries on demand.`}
                </div>
            ),
            primaryButton: {
                children: isEnabling ? 'Enable' : 'Disable',
                type: 'primary',
                status: isEnabling ? undefined : 'danger',
                onClick: () => updateVersionMaterialization(item.version, { is_materialized: isEnabling }),
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const columns: LemonTableColumns<EndpointVersionType> = [
        {
            title: 'Version',
            dataIndex: 'version',
            render: function RenderVersion(_, item) {
                const isLatest = item.version === endpoint.current_version
                const isViewing = viewingVersion === item.version
                const versionUrl = isLatest
                    ? urls.endpoint(endpoint.name)
                    : `${urls.endpoint(endpoint.name)}?version=${item.version}`

                return (
                    <LemonTableLink
                        to={versionUrl}
                        title={
                            <div className="flex items-center gap-2">
                                <span>v{item.version}</span>
                                {isViewing && (
                                    <LemonTag size="small" type="warning">
                                        Currently viewing
                                    </LemonTag>
                                )}
                            </div>
                        }
                        description={
                            item.description
                                ? item.description.length > 40
                                    ? `${item.description.slice(0, 40)}...`
                                    : item.description
                                : undefined
                        }
                    />
                )
            },
        },
        {
            title: 'Created at',
            dataIndex: 'created_at',
            render: function RenderCreatedAt(_, item) {
                return item.created_at ? <TZLabel time={item.created_at} /> : <span className="text-muted">—</span>
            },
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: function RenderCreatedBy(_, item) {
                return item.created_by ? (
                    <ProfilePicture user={item.created_by} size="md" showName />
                ) : (
                    <span className="text-muted">—</span>
                )
            },
        },
        {
            title: 'Active',
            align: 'center',
            render: function RenderActive(_, item) {
                const isLatest = item.version === endpoint.current_version
                const active = isLatest ? endpoint.is_active : item.is_active

                return (
                    <LemonTag type={active ? 'success' : 'default'} size="small">
                        {active ? 'Active' : 'Inactive'}
                    </LemonTag>
                )
            },
        },
        {
            title: 'Materialization',
            align: 'center',
            render: function RenderMaterialization(_, item) {
                const isLatest = item.version === endpoint.current_version
                const isMaterialized = isLatest ? endpoint.is_materialized : item.is_materialized
                const materialization = isLatest ? endpoint.materialization : item.materialization

                const { label, type } = getMaterializationStatusDisplay(isMaterialized, materialization)

                return (
                    <LemonTag type={type} size="small">
                        {label}
                    </LemonTag>
                )
            },
        },
        {
            key: 'actions',
            width: 0,
            render: function RenderActions(_, item) {
                const isLatest = item.version === endpoint.current_version
                const active = isLatest ? endpoint.is_active : item.is_active
                const materialized = isLatest ? endpoint.is_materialized : item.is_materialized

                return (
                    <More
                        overlay={
                            <>
                                <LemonButton onClick={() => selectVersion(item.version)} fullWidth>
                                    View endpoint version
                                </LemonButton>
                                <LemonButton onClick={() => handleToggleVersionActive(item, isLatest)} fullWidth>
                                    {active ? 'Deactivate' : 'Activate'} endpoint version
                                </LemonButton>
                                <LemonButton onClick={() => handleToggleMaterialization(item, materialized)} fullWidth>
                                    {materialized
                                        ? 'Disable version materialization'
                                        : 'Enable version materialization'}
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="max-w-5xl">
            <p className="text-muted mb-3">
                Versions are created automatically when the query changes. Click on a version to view its details.
            </p>
            <LemonTable
                dataSource={sortedVersions}
                columns={columns}
                loading={versionsLoading}
                rowKey="version"
                pagination={{ pageSize: 10, hideOnSinglePage: true }}
                emptyState="No versions yet"
            />
        </div>
    )
}
