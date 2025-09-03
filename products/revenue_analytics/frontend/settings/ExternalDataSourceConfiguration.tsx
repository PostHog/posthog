import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { cn } from 'lib/utils/css-classes'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ExternalDataSource, PipelineNodeTab, PipelineStage } from '~/types'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

const VALID_REVENUE_SOURCES: ExternalDataSource['source_type'][] = ['Stripe']

export function ExternalDataSourceConfiguration({
    buttonRef,
}: {
    buttonRef?: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { dataWarehouseSources, joins } = useValues(revenueAnalyticsSettingsLogic)
    const { updateSource } = useActions(revenueAnalyticsSettingsLogic)
    const { toggleEditJoinModal, toggleNewJoinModal } = useActions(viewLinkLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    const revenueSources =
        dataWarehouseSources?.results.filter((source) => VALID_REVENUE_SOURCES.includes(source.source_type)) ?? []

    return (
        <SceneSection
            hideTitleAndDescription={!newSceneLayout}
            className={cn(!newSceneLayout && 'gap-y-0')}
            title="Data warehouse sources configuration"
            description="PostHog can display revenue data in our Revenue Analytics product from the following data warehouse sources. You can enable/disable each source to stop it from being used for revenue data. You can also configure how we join your revenue data to the PostHog persons table - when this is set, we'll be able to properly display revenue for a person via the persons.$virt_revenue and persons.$virt_revenue_last_30_days virtual fields."
        >
            {!newSceneLayout && (
                <>
                    <h3 className="mb-2">Data warehouse sources configuration</h3>
                    <p className="mb-4">
                        PostHog can display revenue data in our Revenue Analytics product from the following data
                        warehouse sources. You can enable/disable each source to stop it from being used for revenue
                        data. You can also configure how we join your revenue data to the PostHog <code>persons</code>{' '}
                        table - when this is set, we'll be able to properly display revenue for a person via the{' '}
                        <code>persons.$virt_revenue</code> and <code>persons.$virt_revenue_last_30_days</code> virtual
                        fields.
                    </p>
                </>
            )}
            <div className={cn('flex flex-col items-end w-full', !newSceneLayout && 'mb-1')}>
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
                        key: 'persons_join',
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
                                <span className="flex flex-row items-center gap-2 my-2">
                                    <span>
                                        Joined to <code>persons</code> via:
                                    </span>

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
                                        >
                                            Add join
                                        </LemonButton>
                                    )}
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
                        render: (_, item: ExternalDataSource) => {
                            const itemPrefix = item.prefix
                                ? `${item.source_type.toLowerCase()}.${item.prefix.replace(/_+$/, '')}`
                                : item.source_type.toLowerCase()
                            const joinName = `${itemPrefix}.customer_revenue_view`
                            const join = joins.find(
                                (join) => join.source_table_name === joinName && join.joining_table_name === 'groups'
                            )

                            return (
                                <span className="flex flex-row items-center gap-2 my-2">
                                    <span>
                                        Joined to <code>groups</code> via:
                                    </span>

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
                                            icon={<IconPlus />}
                                            onClick={() =>
                                                // This is all very hardcoded, but it's the exact kind of join we want to add
                                                // and that we're expecting in the backend.
                                                toggleNewJoinModal({
                                                    source_table_name: joinName,
                                                    source_table_key: 'id',
                                                    joining_table_name: 'groups',
                                                    joining_table_key: 'group_key',
                                                    field_name: 'groups',
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
        </SceneSection>
    )
}
