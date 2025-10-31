import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { liveDebuggerLogic } from './liveDebuggerLogic'

export const scene: SceneExport = {
    component: LiveDebugger,
    logic: liveDebuggerLogic,
}

export function LiveDebugger(): JSX.Element {
    const isEnabled = useFeatureFlag('LIVE_DEBUGGER')

    if (!isEnabled) {
        return <NotFound object="Live debugger" caption="This feature is not enabled for your project." />
    }

    return (
        <>
            <SceneTitleSection
                name="Live Debugger"
                description="Set breakpoints in your code to capture and inspect runtime values"
                resourceType={{
                    type: 'live_debugger',
                }}
            />

            <SceneDivider />

            <SceneContent>
                <h1>Live Debugger!</h1>
            </SceneContent>
        </>
    )
}
