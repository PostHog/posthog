import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { Text } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BASE_CURRENCY_DESCRIPTION, BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DefinitionsSceneTabs } from 'scenes/data-management/DefinitionsSceneTabs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { RevenueAnalyticsEventItem } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { sourceManagementLogic } from 'products/data_warehouse/frontend/shared/logics/sourceManagementLogic'

import { DataWarehouseManagedViewsetConfiguration } from './DataWarehouseManagedViewsetConfiguration'
import { EventConfiguration } from './EventConfiguration'
import { EventConfigurationModal } from './EventConfigurationModal'
import { ExternalDataSourceConfiguration } from './ExternalDataSourceConfiguration'
import { FilterTestAccountsConfiguration } from './FilterTestAccountsConfiguration'
import { QuillRevenueSourcesEmpty } from './QuillRevenueSourcesEmpty'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

export function RevenueAnalyticsSettings(): JSX.Element {
    const [eventModalState, setEventModalState] = useState<{
        isOpen: boolean
        event?: RevenueAnalyticsEventItem
    }>({ isOpen: false })

    const { events } = useValues(revenueAnalyticsSettingsLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(sourceManagementLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const managedViewsetsEnabled = featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]
    const isViewsetEnabled = currentTeam?.managed_viewsets?.['revenue_analytics'] ?? false

    const hasNoEvents = !events.length
    const hasNoDataWarehouseSources =
        !dataWarehouseSourcesLoading &&
        !dataWarehouseSources?.results.filter((source) => source.source_type === 'Stripe').length
    const hasNoRevenueSources = hasNoEvents && hasNoDataWarehouseSources

    const shouldBlockSettings = managedViewsetsEnabled && !isViewsetEnabled

    const { reportRevenueAnalyticsSettingsViewed } = useActions(eventUsageLogic)
    useOnMountEffect(() => reportRevenueAnalyticsSettingsViewed())

    const openEventModal = (event?: RevenueAnalyticsEventItem): void => {
        setEventModalState({ isOpen: true, event })
    }
    const closeEventModal = (): void => {
        setEventModalState({ isOpen: false, event: undefined })
    }
    const importFromDataWarehouse = (): void => {
        router.actions.push(urls.dataWarehouseSourceNew('stripe'))
    }

    const baseCurrency = (
        <AccessControlAction
            resourceType={AccessControlResourceType.RevenueAnalytics}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <BaseCurrency hideTitle={todayRailNav} />
        </AccessControlAction>
    )

    return (
        <QuillSurfaceContext.Provider value={todayRailNav}>
            <SceneContent>
                <DefinitionsSceneTabs activeKey="revenue" />
                <SceneTitleSection
                    name="Revenue analytics"
                    resourceType={{
                        type: 'revenue_analytics',
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
                        {todayRailNav ? (
                            // BaseCurrency keeps the description size that Settings shows, so this page sets the
                            // xs description that its other sections use.
                            <SceneSection title="Base currency">
                                <Text size="xs" render={<p className="m-0 max-w-160" />}>
                                    {BASE_CURRENCY_DESCRIPTION}
                                </Text>
                                {baseCurrency}
                            </SceneSection>
                        ) : (
                            baseCurrency
                        )}
                        <SceneDivider />

                        <FilterTestAccountsConfiguration />
                        <SceneDivider />

                        {todayRailNav ? (
                            hasNoRevenueSources && (
                                <QuillRevenueSourcesEmpty
                                    onAddEvent={() => openEventModal()}
                                    onImportFromDataWarehouse={importFromDataWarehouse}
                                />
                            )
                        ) : (
                            <ProductIntroduction
                                thingName="revenue source"
                                description=""
                                isEmpty={hasNoRevenueSources}
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
                                                    onClick={importFromDataWarehouse}
                                                    data-attr="import-revenue-data-warehouse-tables"
                                                >
                                                    Import revenue data from data warehouse
                                                </LemonButton>
                                            </AccessControlAction>

                                            <span className="text-xs text-muted-alt">
                                                Only Stripe is supported currently. <br />
                                                <Link to="https://posthog.com/roadmap">
                                                    Request more revenue integrations.
                                                </Link>
                                            </span>
                                        </div>
                                    </>
                                }
                            />
                        )}

                        <ExternalDataSourceConfiguration />
                        <SceneDivider />

                        <EventConfiguration onOpenEventModal={openEventModal} />
                    </>
                )}

                {eventModalState.isOpen && (
                    <EventConfigurationModal event={eventModalState.event} onClose={closeEventModal} />
                )}
            </SceneContent>
        </QuillSurfaceContext.Provider>
    )
}
