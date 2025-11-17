import { useActions, useValues } from 'kea'

import { LemonBanner, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { DataWarehouseManagedViewsetCard } from 'scenes/data-management/managed-viewsets/DataWarehouseManagedViewsetCard'
import { DataWarehouseManagedViewsetImpactModal } from 'scenes/data-management/managed-viewsets/DataWarehouseManagedViewsetImpactModal'
import { disableDataWarehouseManagedViewsetModalLogic } from 'scenes/data-management/managed-viewsets/disableDataWarehouseManagedViewsetModalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { AccessControlResourceType } from '~/types'

export function DataWarehouseManagedViewsetConfiguration(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)
    const { views } = useValues(disableDataWarehouseManagedViewsetModalLogic({ type: 'ManagedViewsetConfiguration' }))

    const isEnabled = currentTeam?.managed_viewsets?.['revenue_analytics'] ?? false

    const onConfirmDisable = async (): Promise<boolean> => {
        try {
            await api.dataWarehouseManagedViewsets.toggle('revenue_analytics', false)
            lemonToast.success('Revenue analytics disabled successfully')
            loadCurrentTeam()
            return true
        } catch (error: any) {
            lemonToast.error(`Failed to disable revenue analytics: ${error.message || 'Unknown error'}`)
            return false
        }
    }

    return (
        <>
            <SceneSection
                title="Revenue analytics"
                description="Revenue analytics must be enabled to automatically create and maintain optimized database views for your revenue data. Once enabled, you can configure which revenue sources and events to track below."
            >
                {!isEnabled && (
                    <LemonBanner type="warning" className="mb-4">
                        <div className="flex items-center gap-2">
                            <span>
                                <strong>Revenue analytics is currently disabled.</strong> Enable it below to start
                                configuring revenue sources and events.
                            </span>
                        </div>
                    </LemonBanner>
                )}

                <DataWarehouseManagedViewsetCard
                    type="ManagedViewsetConfiguration"
                    kind="revenue_analytics"
                    displayConfigLink={false}
                    resourceType={AccessControlResourceType.RevenueAnalytics}
                />
            </SceneSection>

            <DataWarehouseManagedViewsetImpactModal
                type="ManagedViewsetConfiguration"
                title="Disable revenue analytics?"
                action={onConfirmDisable}
                confirmText="revenue_analytics"
                views={views}
                warningItems={[
                    'Permanently delete all revenue views',
                    'Break any existing queries, insights, or dashboards that reference these views',
                    'Stop all scheduled materialization jobs',
                    'Disable all revenue analytics functionality',
                ]}
                infoMessage={
                    <>
                        <strong>Important:</strong> Disabling revenue analytics will remove all revenue data views. You
                        can re-enable it later, but views will need to be rebuilt from your configured sources.
                    </>
                }
                viewsActionText="will be deleted"
                confirmButtonText="Yes, disable revenue analytics"
            />
        </>
    )
}
