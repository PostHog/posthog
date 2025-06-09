import { LemonButton, LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { ExternalDataSource, PipelineNodeTab, PipelineStage } from '~/types'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

const VALID_REVENUE_SOURCES: ExternalDataSource['source_type'][] = ['Stripe']

export function ExternalDataSourceConfiguration({
    buttonRef,
}: {
    buttonRef?: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { dataWarehouseSources } = useValues(revenueAnalyticsSettingsLogic)
    const { updateSource } = useActions(revenueAnalyticsSettingsLogic)

    const revenueSources =
        dataWarehouseSources?.results.filter((source) => VALID_REVENUE_SOURCES.includes(source.source_type)) ?? []

    return (
        <div>
            <h3 className="mb-2">Data Warehouse Sources Configuration</h3>
            <p className="mb-4">
                PostHog can display revenue data in our Revenue Analytics product from the following data warehouse
                sources. You can enable/disable each source to stop it from being used for revenue data.
            </p>
            <LemonTable
                rowKey={(item) => item.id}
                loading={dataWarehouseSources === null}
                dataSource={revenueSources}
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
                                    {item.prefix || item.source_type}
                                </Link>
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
                    {
                        key: 'actions',
                        width: 0,
                        title: (
                            <LemonButton
                                className="my-1"
                                ref={buttonRef}
                                type="primary"
                                onClick={() => {
                                    router.actions.push(
                                        urls.pipelineNodeNew(PipelineStage.Source, { source: 'Stripe' })
                                    )
                                }}
                            >
                                Add new source
                            </LemonButton>
                        ),
                        render: () => null,
                    },
                ]}
            />
        </div>
    )
}
