import { useActions, useValues } from 'kea'

import { LemonBanner, lemonToast } from '@posthog/lemon-ui'
import { Item, ItemContent, ItemDescription } from '@posthog/quill'

import api from 'lib/api'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { DataWarehouseManagedViewsetCard } from 'scenes/data-management/managed-viewsets/DataWarehouseManagedViewsetCard'
import { DataWarehouseManagedViewsetImpactModal } from 'scenes/data-management/managed-viewsets/DataWarehouseManagedViewsetImpactModal'
import { disableDataWarehouseManagedViewsetModalLogic } from 'scenes/data-management/managed-viewsets/disableDataWarehouseManagedViewsetModalLogic'
import { QuillDataWarehouseManagedViewsetCard } from 'scenes/data-management/managed-viewsets/QuillDataWarehouseManagedViewsetCard'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlResourceType } from '~/types'

const DISABLED_MESSAGE = (
    <>
        <strong>Revenue analytics is currently disabled.</strong> Enable it below to start configuring revenue sources
        and events.
    </>
)

export function DataWarehouseManagedViewsetConfiguration(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)
    const quillSurface = useQuillSurface()
    const { views } = useValues(disableDataWarehouseManagedViewsetModalLogic({ type: 'ManagedViewsetConfiguration' }))

    const isEnabled = currentTeam?.managed_viewsets?.['revenue_analytics'] ?? false

    const onConfirmDisable = async (): Promise<boolean> => {
        try {
            await api.dataWarehouseManagedViewsets.toggle('revenue_analytics', false)
            await api.revenueAnalyticsJoins.sync(false)
            lemonToast.success('Revenue analytics disabled successfully')
            loadCurrentTeam()
            return true
        } catch (error: any) {
            lemonToast.error(`Failed to disable revenue analytics: ${error.message || 'Unknown error'}`)
            return false
        }
    }

    const ViewsetCard = quillSurface ? QuillDataWarehouseManagedViewsetCard : DataWarehouseManagedViewsetCard

    return (
        <>
            {!isEnabled &&
                (quillSurface ? (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>{DISABLED_MESSAGE}</ItemDescription>
                        </ItemContent>
                    </Item>
                ) : (
                    <LemonBanner type="warning">
                        <div className="flex items-center gap-2">
                            <span>{DISABLED_MESSAGE}</span>
                        </div>
                    </LemonBanner>
                ))}

            <ViewsetCard
                type="ManagedViewsetConfiguration"
                kind="revenue_analytics"
                displayConfigLink={false}
                resourceType={AccessControlResourceType.RevenueAnalytics}
            />

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
