import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonTabs, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { RevenueAnalyticsEventItem } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { sourceManagementLogic } from 'products/data_warehouse/frontend/shared/logics/sourceManagementLogic'

import { DataWarehouseManagedViewsetConfiguration } from './DataWarehouseManagedViewsetConfiguration'
import { EventConfiguration } from './EventConfiguration'
import { EventConfigurationModal } from './EventConfigurationModal'
import { ExternalDataSourceConfiguration } from './ExternalDataSourceConfiguration'
import { FilterTestAccountsConfiguration } from './FilterTestAccountsConfiguration'
import { GoalsConfiguration } from './GoalsConfiguration'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'
import { RevenueExampleDataWarehouseTablesData } from './RevenueExampleDataWarehouseTablesData'
import { RevenueExampleEventsTable } from './RevenueExampleEventsTable'

type Tab = 'events' | 'data-warehouse'

export function RevenueAnalyticsSettings(): JSX.Element {
    const [activeTab, setActiveTab] = useState<Tab>('events')
    const [eventModalState, setEventModalState] = useState<{
        isOpen: boolean
        event?: RevenueAnalyticsEventItem
    }>({ isOpen: false })

    const { events } = useValues(revenueAnalyticsSettingsLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(sourceManagementLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)

    const managedViewsetsEnabled = featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]
    const isViewsetEnabled = currentTeam?.managed_viewsets?.['revenue_analytics'] ?? false

    const hasNoEvents = !events.length
    const hasNoDataWarehouseSources =
        !dataWarehouseSourcesLoading &&
        !dataWarehouseSources?.results.filter((source) => source.source_type === 'Stripe').length

    const shouldBlockSettings = managedViewsetsEnabled && !isViewsetEnabled

    const { reportRevenueAnalyticsSettingsViewed } = useActions(eventUsageLogic)
    useOnMountEffect(() => reportRevenueAnalyticsSettingsViewed())

    const openEventModal = (event?: RevenueAnalyticsEventItem): void => {
        setEventModalState({ isOpen: true, event })
    }
    const closeEventModal = (): void => {
        setEventModalState({ isOpen: false, event: undefined })
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.RevenueAnalytics].name}
                description={sceneConfigurations[Scene.RevenueAnalytics].description}
                resourceType={{
                    type: sceneConfigurations[Scene.RevenueAnalytics].iconType || 'default_icon_type',
                }}
            />

            {managedViewsetsEnabled && (
                <>
                    <DataWarehouseManagedViewsetConfiguration />
                    <SceneDivider />
                </>
            )}

            {shouldBlockSettings ? null : (
                <>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.RevenueAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <BaseCurrency />
                    </AccessControlAction>
                    <SceneDivider />

                    <FilterTestAccountsConfiguration />
                    <SceneDivider />

                    <GoalsConfiguration />
                    <SceneDivider />

                    <ProductIntroduction
                        productName="Revenue tracking"
                        thingName="revenue source"
                        description={sceneConfigurations[Scene.RevenueAnalytics].description || ''}
                        isEmpty={hasNoEvents && hasNoDataWarehouseSources}
                        actionElementOverride={
                            <>
                                <div className="flex flex-col gap-2">
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.RevenueAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                    >
                                        <LemonButton
                                            type="primary"
                                            icon={<IconPlus />}
                                            onClick={() => openEventModal()}
                                            data-attr="create-revenue-event"
                                        >
                                            Add revenue event
                                        </LemonButton>
                                    </AccessControlAction>

                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.RevenueAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                    >
                                        <LemonButton
                                            type="primary"
                                            icon={<IconPlus />}
                                            onClick={() => {
                                                router.actions.push(urls.dataWarehouseSourceNew('stripe'))
                                            }}
                                            data-attr="import-revenue-data-warehouse-tables"
                                        >
                                            Import revenue data from data warehouse
                                        </LemonButton>
                                    </AccessControlAction>

                                    <span className="text-xs text-muted-alt">
                                        Only Stripe is supported currently. <br />
                                        <Link to="https://github.com/PostHog/posthog/issues/new?assignees=&labels=enhancement,feature/revenue-analytics%2C+feature&projects=&template=feature_request.yml&title=New%20revenue%20source:%20%3Cinsert%20source%3E">
                                            Request more revenue integrations.
                                        </Link>
                                    </span>
                                </div>
                            </>
                        }
                    />

                    <ExternalDataSourceConfiguration />
                    <SceneDivider />

                    <EventConfiguration onOpenEventModal={openEventModal} />
                    <SceneDivider />

                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key as Tab)}
                        tabs={[
                            {
                                key: 'data-warehouse',
                                label: 'Data Warehouse revenue events',
                                content: <RevenueExampleDataWarehouseTablesData />,
                            },
                            {
                                key: 'events',
                                label: 'Revenue events',
                                content: <RevenueExampleEventsTable />,
                            },
                        ]}
                    />
                </>
            )}

            {eventModalState.isOpen && (
                <EventConfigurationModal event={eventModalState.event} onClose={closeEventModal} />
            )}
        </SceneContent>
    )
}
