import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconInfo, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch, Link, Spinner, Tooltip, lemonToast } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { DataWarehouseManagedViewsetImpactModal } from 'scenes/data-management/managed-viewsets/DataWarehouseManagedViewsetImpactModal'
import { disableDataWarehouseManagedViewsetModalLogic } from 'scenes/data-management/managed-viewsets/disableDataWarehouseManagedViewsetModalLogic'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { AccessControlLevel, AccessControlResourceType, ExternalDataSource } from '~/types'

import { disableRevenueSourceModalLogic } from './disableRevenueSourceModalLogic'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

const VALID_REVENUE_SOURCES: ExternalDataSource['source_type'][] = ['Stripe']

export function ExternalDataSourceConfiguration({
    buttonRef,
}: {
    buttonRef?: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading, joins } = useValues(revenueAnalyticsSettingsLogic)
    const { views, source: sourceToBeDisabled } = useValues(disableRevenueSourceModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { updateSourceRevenueAnalyticsConfig, deleteJoin } = useActions(revenueAnalyticsSettingsLogic)
    const { toggleEditJoinModal, toggleNewJoinModal } = useActions(viewLinkLogic)
    const { openModal } = useActions(
        disableDataWarehouseManagedViewsetModalLogic({ type: 'ExternalDataSourceConfiguration' })
    )
    const { setSource: setSourceToBeDisabled } = useActions(disableRevenueSourceModalLogic)

    const managedViewsetsEnabled = featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]

    const revenueSources =
        dataWarehouseSources?.results.filter((source) => VALID_REVENUE_SOURCES.includes(source.source_type)) ?? []

    const disabledReasonForRevenueAnalyticsConfig = (source: ExternalDataSource): string | undefined => {
        if (!source.revenue_analytics_config.enabled) {
            return 'Revenue analytics is not enabled for this source'
        }
        if (dataWarehouseSourcesLoading) {
            return 'Updating...'
        }
        return undefined
    }

    const onDisableSource = async (): Promise<boolean> => {
        if (!sourceToBeDisabled) {
            return false
        }

        try {
            updateSourceRevenueAnalyticsConfig({
                source: sourceToBeDisabled,
                config: { enabled: false },
            })
            setSourceToBeDisabled(null)

            lemonToast.success(`Revenue analytics disabled for ${sourceToBeDisabled.source_type}`)
            return true
        } catch (error: any) {
            lemonToast.error(`Failed to disable source: ${error.message || 'Unknown error'}`)
            return false
        }
    }

    return (
        <SceneSection
            title="Data warehouse sources configuration"
            description="PostHog can display revenue data in our Revenue Analytics product from the following data warehouse sources. You can enable/disable each source to stop it from being used for revenue data. You can also configure how we join your revenue data to the PostHog persons table - when this is set, we'll be able to properly display revenue for a person via the persons.$virt_revenue and persons.$virt_revenue_last_30_days virtual fields."
        >
            <div className={cn('flex flex-col items-end w-full')}>
                <AccessControlAction
                    resourceType={AccessControlResourceType.RevenueAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        className="my-1"
                        ref={buttonRef}
                        type="primary"
                        icon={<IconPlus />}
                        size="small"
                        onClick={() => {
                            router.actions.push(urls.dataWarehouseSourceNew('stripe'))
                        }}
                    >
                        Add new source
                    </LemonButton>
                </AccessControlAction>
            </div>
            <LemonTable
                rowKey={(item) => item.id}
                loading={dataWarehouseSources === null}
                dataSource={revenueSources}
                emptyState="No DWH revenue sources configured yet"
                columns={[
                    {
                        key: 'source',
                        title: '',
                        width: 0,
                        render: (_, source: ExternalDataSource) => {
                            if (dataWarehouseSourcesLoading) {
                                return <Spinner size="medium" />
                            }

                            return <DataWarehouseSourceIcon type={source.source_type} />
                        },
                    },
                    {
                        key: 'prefix',
                        title: 'Source',
                        render: (_, source: ExternalDataSource) => {
                            return (
                                <span className="inline-flex items-centet gap-2">
                                    <Link to={urls.dataWarehouseSource(`managed-${source.id}`)}>
                                        {source.source_type}&nbsp;{source.prefix && `(${source.prefix})`}
                                    </Link>
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.RevenueAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                    >
                                        <LemonSwitch
                                            checked={source.revenue_analytics_config.enabled}
                                            disabledReason={dataWarehouseSourcesLoading ? 'Updating...' : undefined}
                                            onChange={(checked) => {
                                                if (!checked && managedViewsetsEnabled) {
                                                    // Show confirmation modal when disabling (if feature flag enabled)
                                                    setSourceToBeDisabled(source)
                                                    openModal('revenue_analytics')
                                                } else {
                                                    // Enable directly without confirmation, or disable directly if feature flag is off
                                                    updateSourceRevenueAnalyticsConfig({
                                                        source,
                                                        config: { enabled: checked },
                                                    })
                                                }
                                            }}
                                        />
                                    </AccessControlAction>
                                </span>
                            )
                        },
                    },
                    {
                        key: 'persons_join',
                        title: (
                            <span>
                                Persons Join
                                <Tooltip title="How do you want to join persons to this source in Revenue Analytics?">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        render: (_, source: ExternalDataSource) => {
                            const sourcePrefix = source.prefix
                                ? `${source.source_type.toLowerCase()}.${source.prefix.replace(/_+$/, '')}`
                                : source.source_type.toLowerCase()
                            const joinName = `${sourcePrefix}.customer_revenue_view`
                            const join = joins.find(
                                (join) => join.source_table_name === joinName && join.joining_table_name === 'persons'
                            )

                            return (
                                <span className="flex flex-row flex-nowrap items-center gap-2 my-2 min-w-[300px]">
                                    <span className="whitespace-nowrap">
                                        Joined to <code>persons</code> via:
                                    </span>

                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.RevenueAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                    >
                                        {({ disabledReason }) =>
                                            join && source.revenue_analytics_config.enabled ? (
                                                <>
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        onClick={() => toggleEditJoinModal(join)}
                                                        disabledReason={
                                                            disabledReasonForRevenueAnalyticsConfig(source) ??
                                                            disabledReason
                                                        }
                                                    >
                                                        {join.source_table_name}.{join.source_table_key}
                                                    </LemonButton>

                                                    <LemonButton
                                                        type="secondary"
                                                        status="danger"
                                                        size="small"
                                                        tooltip="Delete join"
                                                        icon={<IconTrash />}
                                                        disabledReason={disabledReason}
                                                        onClick={() => deleteJoin(join)}
                                                    />
                                                </>
                                            ) : (
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    icon={<IconPlus />}
                                                    onClick={() =>
                                                        // This is all very hardcoded, but it's the exact kind of join we want to add
                                                        // and that we're expecting in the backend.
                                                        toggleNewJoinModal({
                                                            source_table_name: joinName,
                                                            source_table_key: 'id',
                                                            joining_table_name: 'persons',
                                                            joining_table_key: 'pdi.distinct_id',
                                                            field_name: 'persons',
                                                        })
                                                    }
                                                    disabledReason={
                                                        disabledReasonForRevenueAnalyticsConfig(source) ??
                                                        disabledReason
                                                    }
                                                >
                                                    Add join
                                                </LemonButton>
                                            )
                                        }
                                    </AccessControlAction>
                                </span>
                            )
                        },
                    },
                    {
                        key: 'groups_join',
                        title: (
                            <span>
                                Groups Join
                                <Tooltip title="How do you want to join groups to this source in Revenue Analytics?">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        render: (_, source: ExternalDataSource) => {
                            const sourcePrefix = source.prefix
                                ? `${source.source_type.toLowerCase()}.${source.prefix.replace(/_+$/, '')}`
                                : source.source_type.toLowerCase()
                            const joinName = `${sourcePrefix}.customer_revenue_view`
                            const join = joins.find(
                                (join) => join.source_table_name === joinName && join.joining_table_name === 'groups'
                            )

                            return (
                                <span className="flex flex-row flex-nowrap items-center gap-2 my-2 min-w-[300px]">
                                    <span className="whitespace-nowrap">
                                        Joined to <code>groups</code> via:
                                    </span>

                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.RevenueAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                    >
                                        {({ disabledReason }) =>
                                            join && source.revenue_analytics_config.enabled ? (
                                                <>
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        onClick={() => toggleEditJoinModal(join)}
                                                        disabledReason={
                                                            disabledReasonForRevenueAnalyticsConfig(source) ??
                                                            disabledReason
                                                        }
                                                        tooltip="Edit join"
                                                    >
                                                        {join.source_table_name}.{join.source_table_key}
                                                    </LemonButton>

                                                    <LemonButton
                                                        type="secondary"
                                                        status="danger"
                                                        size="small"
                                                        tooltip="Delete join"
                                                        icon={<IconTrash />}
                                                        onClick={() => deleteJoin(join)}
                                                        disabledReason={disabledReason}
                                                    />
                                                </>
                                            ) : (
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    icon={<IconPlus />}
                                                    onClick={() =>
                                                        // This is all very hardcoded, but it's the exact kind of join we want to add
                                                        // and that we're expecting in the backend.
                                                        toggleNewJoinModal({
                                                            source_table_name: joinName,
                                                            source_table_key: 'id',
                                                            joining_table_name: 'groups',
                                                            joining_table_key: 'key',
                                                            field_name: 'groups',
                                                        })
                                                    }
                                                    disabledReason={
                                                        disabledReasonForRevenueAnalyticsConfig(source) ??
                                                        disabledReason
                                                    }
                                                >
                                                    Add join
                                                </LemonButton>
                                            )
                                        }
                                    </AccessControlAction>
                                </span>
                            )
                        },
                    },
                    {
                        key: 'separator',
                        title: <LemonDivider vertical className="py-1 h-[16px]" />,
                    },
                    {
                        key: 'include_invoiceless_charges',
                        title: (
                            <span>
                                Include invoiceless charges
                                <Tooltip title="By default, Revenue analytics considers both your invoices and any invoiceless charges when calculating your revenue - and exposing it through the `revenue_item` views. Disable this if we should only consider your invoices and omit charges from the calculations.">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        render: (_, source: ExternalDataSource) => {
                            return (
                                <LemonSwitch
                                    checked={
                                        source.revenue_analytics_config.enabled &&
                                        source.revenue_analytics_config.include_invoiceless_charges
                                    }
                                    disabledReason={disabledReasonForRevenueAnalyticsConfig(source)}
                                    onChange={(checked) =>
                                        updateSourceRevenueAnalyticsConfig({
                                            source,
                                            config: { include_invoiceless_charges: checked },
                                        })
                                    }
                                />
                            )
                        },
                    },
                ]}
            />

            {/* To be used above by the join features */}
            <ViewLinkModal mode="revenue_analytics" />
            {managedViewsetsEnabled && (
                <DataWarehouseManagedViewsetImpactModal
                    type="ExternalDataSourceConfiguration"
                    title={`Disable revenue analytics for ${sourceToBeDisabled ? `${sourceToBeDisabled.source_type}${sourceToBeDisabled.prefix ? ` (${sourceToBeDisabled.prefix})` : ''}` : ''}?`}
                    action={onDisableSource}
                    confirmText={sourceToBeDisabled?.prefix || sourceToBeDisabled?.source_type || ''}
                    views={views}
                    warningItems={[
                        'Permanently delete all revenue views created from this source',
                        'Break any existing queries, insights, or dashboards that reference these views',
                        'Stop all scheduled materialization jobs for these views',
                    ]}
                    infoMessage={
                        <>
                            <strong>Important:</strong> The source will no longer be included in revenue calculations
                            for revenue analytics. It'll also trigger re-materialization of all remaining revenue views.
                        </>
                    }
                    viewsActionText="will be deleted"
                    confirmButtonText="Yes, disable source"
                />
            )}
        </SceneSection>
    )
}
