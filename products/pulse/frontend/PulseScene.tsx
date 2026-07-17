import { IconPulse } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: PulseScene,
}

export function PulseScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PULSE')

    if (!isEnabled) {
        return <NotFound object="Pulse" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Pulse"
                description="Recurring product briefs: what happened, why it happened, and what to build next."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconPulse /> }}
            />
        </SceneContent>
    )
}
