import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { featureFlagsStaffToolsLogic } from './featureFlagsStaffToolsLogic'
import { StaffCacheToolsTab } from './StaffCacheToolsTab'

export const scene: SceneExport = {
    component: FeatureFlagsStaffToolsScene,
    logic: featureFlagsStaffToolsLogic,
}

export function FeatureFlagsStaffToolsScene(): JSX.Element {
    const { user } = useValues(userLogic)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="This page is only accessible to staff users." />
    }

    return (
        <SceneContent>
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h1 className="text-xl font-bold">Flags staff tools</h1>
                    <p className="text-sm text-secondary mt-1">
                        Look up any team across all organizations to inspect and rebuild its flag caches.
                    </p>
                </div>
                <LemonButton type="tertiary" size="small" to={urls.instanceSettings()}>
                    Flags-related instance settings
                </LemonButton>
            </div>
            <StaffCacheToolsTab />
        </SceneContent>
    )
}
