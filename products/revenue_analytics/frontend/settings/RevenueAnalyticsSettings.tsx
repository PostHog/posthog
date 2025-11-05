import { useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonTabs, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DataWarehouseManagedViewsetConfiguration } from './DataWarehouseManagedViewsetConfiguration'
import { EventConfiguration } from './EventConfiguration'
import { ExternalDataSourceConfiguration } from './ExternalDataSourceConfiguration'
import { FilterTestAccountsConfiguration } from './FilterTestAccountsConfiguration'
import { GoalsConfiguration } from './GoalsConfiguration'
import { RevenueExampleDataWarehouseTablesData } from './RevenueExampleDataWarehouseTablesData'
import { RevenueExampleEventsTable } from './RevenueExampleEventsTable'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

type Tab = 'events' | 'data-warehouse'

export function RevenueAnalyticsSettings(): JSX.Element {
    const [activeTab, setActiveTab] = useState<Tab>('events')

    const { events } = useValues(revenueAnalyticsSettingsLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)

    const eventsButtonRef = useRef<HTMLButtonElement>(null)
    const dataWarehouseTablesButtonRef = useRef<HTMLButtonElement>(null)

    const managedViewsetsEnabled = featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]
    const isViewsetEnabled = currentTeam?.managed_viewsets?.['revenue_analytics'] ?? false

    const hasNoEvents = !events.length
    const hasNoDataWarehouseSources =
        !dataWarehouseSourcesLoading &&
        !dataWarehouseSources?.results.filter((source) => source.source_type === 'Stripe').length

    const shouldBlockSettings = managedViewsetsEnabled && !isViewsetEnabled

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.RevenueAnalytics].name}
                description={sceneConfigurations[Scene.RevenueAnalytics].description}
                resourceType={{
                    type: sceneConfigurations[Scene.RevenueAnalytics].iconType || 'default_icon_type',
                }}
            />
            <SceneDivider />

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
                                            onClick={() => {
                                                eventsButtonRef.current?.scrollIntoView({ behavior: 'smooth' })
                                                eventsButtonRef.current?.click()
                                            }}
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
                                                dataWarehouseTablesButtonRef.current?.scrollIntoView({
                                                    behavior: 'smooth',
                                                })
                                                dataWarehouseTablesButtonRef.current?.click()
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

                    <ExternalDataSourceConfiguration buttonRef={dataWarehouseTablesButtonRef} />
                    <SceneDivider />

                    <EventConfiguration buttonRef={eventsButtonRef} />
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
        </SceneContent>
    )
}
