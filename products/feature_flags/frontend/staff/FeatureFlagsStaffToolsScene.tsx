import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

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
            <SceneTitleSection
                name="Flags staff tools"
                description="Look up any team across all organizations to inspect and rebuild its flag caches."
                resourceType={{ type: 'feature_flag' }}
                actions={
                    <LemonButton type="secondary" size="small" to={urls.instanceSettings()}>
                        Flags-related instance settings
                    </LemonButton>
                }
            />
            <StaffCacheToolsTab />
        </SceneContent>
    )
}
