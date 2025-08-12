import { LemonButton, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'
import { ExternalDataSource, PipelineNodeTab, PipelineStage } from '~/types'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'
import { IconInfo, IconPlus } from '@posthog/icons'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'

const VALID_REVENUE_SOURCES: ExternalDataSource['source_type'][] = ['Stripe']

export function ExternalDataSourceConfiguration({
    buttonRef,
}: {
    buttonRef?: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { dataWarehouseSources, joins } = useValues(revenueAnalyticsSettingsLogic)
    const { updateSource } = useActions(revenueAnalyticsSettingsLogic)
    const { toggleEditJoinModal, toggleNewJoinModal } = useActions(viewLinkLogic)

    const revenueSources =
        dataWarehouseSources?.results.filter((source) => VALID_REVENUE_SOURCES.includes(source.source_type)) ?? []

    return (
        <div>
            <h3 className="mb-2">Data Warehouse Sources Configuration</h3>
            <p className="mb-4">
                PostHog can display revenue data in our Revenue Analytics product from the following data warehouse
                sources. You can enable/disable each source to stop it from being used for revenue data. You can also
                configure how we join your revenue data to the PostHog <code>persons</code> table - when this is set,
                we'll be able to properly display revenue for a person via the <code>persons.$virt_revenue</code> and{' '}
                <code>persons.$virt_revenue_last_30_days</code> virtual fields.
            </p>
            <div className="flex flex-col mb-1 items-end w-full">
                <LemonButton
                    className="my-1"
                    ref={buttonRef}
                    type="primary"
                    icon={<IconPlus />}
                    size="small"
                    onClick={() => {
                        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source, { source: 'Stripe' }))
                    }}
                >
                    Add new source
                </LemonButton>
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
                        render: (_, item: ExternalDataSource) => {
                            return <DataWarehouseSourceIcon type={item.source_type} />
                        },
                    },
                    {
                        key: 'prefix',
                        title: 'Source',
                        render: (_, item: ExternalDataSource) => {
                            return (
                                <Link
                                    to={urls.pipelineNode(
                                        PipelineStage.Source,
                                        `managed-${item.id}`,
                                        PipelineNodeTab.Schemas
                                    )}
                                >
                                    {item.source_type}&nbsp;{item.prefix && `(${item.prefix})`}
                                </Link>
                            )
                        },
                    },
                    {
                        key: 'joins',
                        title: (
                            <span>
                                Persons Join
                                <Tooltip title="How do you want to join persons to this source in Revenue Analytics?">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        render: (_, item: ExternalDataSource) => {
                            const itemPrefix = item.prefix
                                ? `${item.source_type.toLowerCase()}.${item.prefix.replace(/_+$/, '')}`
                                : item.source_type.toLowerCase()
                            const joinName = `${itemPrefix}.customer_revenue_view`
                            const join = joins.find(
                                (join) => join.source_table_name === joinName && join.joining_table_name === 'persons'
                            )

                            return (
                                <span className="flex flex-row items-center gap-2">
                                    Joined to <code>persons</code> via:
                                    {join ? (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => toggleEditJoinModal(join)}
                                        >
                                            {join.source_table_name}.{join.source_table_key}
                                        </LemonButton>
                                    ) : (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
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
                                        >
                                            Add join
                                        </LemonButton>
                                    )}
                                </span>
                            )
                        },
                    },
                    {
                        key: 'revenue_analytics_enabled',
                        title: 'Enabled?',
                        render: (_, item: ExternalDataSource) => {
                            return (
                                <LemonSwitch
                                    checked={item.revenue_analytics_enabled}
                                    onChange={(checked) =>
                                        updateSource({ ...item, revenue_analytics_enabled: checked })
                                    }
                                />
                            )
                        },
                    },
                ]}
            />

            {/* To be used above by the join features */}
            <ViewLinkModal mode="revenue_analytics" />
        </div>
    )
}
