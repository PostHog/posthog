import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EventStream } from 'products/vision_hog/frontend/EventStream'
import { SceneExport } from 'scenes/sceneTypes'

import { VideoStreamPlayer } from './VideoStreamPlayer'
import { VisionHogConfigScene } from './VisionHogConfigScene'
// import { useActions, useValues } from 'kea' // Uncomment if you use actions/values from logic
import { visionHogSceneLogic } from './visionHogSceneLogic'

export const scene: SceneExport = {
    component: VisionHogScene,
    logic: visionHogSceneLogic,
}

export function VisionHogScene(): JSX.Element {
    const { videoUrl, activeTab } = useValues(visionHogSceneLogic)
    const { setActiveTab } = useActions(visionHogSceneLogic)

    return (
        <div className="w-full max-w-6xl mx-auto">
            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={[
                    {
                        key: 'video',
                        label: 'Video',
                        content: (
                            <div className="flex flex-row w-full max-w-5xl mx-auto gap-8">
                                {/* Left: Video */}
                                <div className="flex-1 w-[640px]">
                                    <div className="w-full flex flex-col items-center border rounded bg-gray-50 p-4 min-h-[640px]">
                                        {videoUrl ? (
                                            <VideoStreamPlayer videoUrl={videoUrl} className="w-full" />
                                        ) : (
                                            <div className="flex items-center justify-center h-[640px] w-full text-gray-500">
                                                Please save config to set video URL
                                            </div>
                                        )}
                                    </div>
                                </div>
                                {/* Right: Events */}
                                <div className="flex-1 border rounded bg-white p-4 min-h-[640px] overflow-y-auto">
                                    <EventStream />
                                </div>
                            </div>
                        ),
                    },
                    {
                        key: 'config',
                        label: 'Config',
                        content: <VisionHogConfigScene />,
                    },
                ]}
            />
        </div>
    )
}
