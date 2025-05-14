import { LemonTabs } from '@posthog/lemon-ui'
import flvjs from 'flv.js'
import Hls from 'hls.js'
import { useActions, useValues } from 'kea'
import { EventStream } from 'products/vision_hog/frontend/EventStream'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { VisionHogConfigScene } from './VisionHogConfigScene'
// import { useActions, useValues } from 'kea' // Uncomment if you use actions/values from logic
import { visionHogSceneLogic } from './visionHogSceneLogic'

const VIDEO_BUFFER_SECONDS = 0

export const scene: SceneExport = {
    component: VisionHogScene,
    logic: visionHogSceneLogic,
}

export function VisionHogScene(): JSX.Element {
    const { videoUrl } = useValues(visionHogSceneLogic)
    const { setVideoUrl } = useActions(visionHogSceneLogic)
    const videoRef = React.useRef<HTMLVideoElement>(null)
    const [videoError, setVideoError] = React.useState<string | null>(null)
    const [activeTab, setActiveTab] = React.useState('video')

    React.useEffect(() => {
        setVideoError(null)
        if (videoUrl && videoRef.current) {
            // Clean up previous sources
            videoRef.current.src = ''
            // HLS
            if (Hls.isSupported() && videoUrl.endsWith('.m3u8')) {
                const hls = new Hls({
                    maxBufferLength: VIDEO_BUFFER_SECONDS,
                })
                hls.loadSource(videoUrl)
                hls.attachMedia(videoRef.current)
                hls.on(Hls.Events.ERROR, () => setVideoError('Could not load video stream.'))
                return () => hls.destroy()
            }
            // FLV
            else if (flvjs.isSupported() && videoUrl.endsWith('.flv')) {
                const flvPlayer = flvjs.createPlayer(
                    {
                        type: 'flv',
                        url: videoUrl,
                        isLive: true,
                    },
                    {
                        enableStashBuffer: true,
                        stashInitialSize: 1.5 * 1024 * 1024 * (VIDEO_BUFFER_SECONDS / 10),
                    }
                )
                flvPlayer.attachMediaElement(videoRef.current)
                flvPlayer.load()
                void flvPlayer.play()
                flvPlayer.on(flvjs.Events.ERROR, () => setVideoError('Could not load video stream.'))
                return () => flvPlayer.destroy()
            }
            // Native (mp4, webm, etc)

            videoRef.current.src = videoUrl
        }
    }, [videoUrl])

    // Native error handling
    const handleVideoError = (): void => setVideoError('Could not load video stream.')

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
                                        <input
                                            type="text"
                                            value={videoUrl}
                                            onChange={(e) => setVideoUrl(e.target.value)}
                                            placeholder="Enter video feed URL"
                                            className="border p-2 rounded w-full mb-4"
                                        />
                                        {!videoUrl ? (
                                            <div className="text-gray-500 text-center my-16">
                                                No video stream. Enter a valid URL above.
                                            </div>
                                        ) : videoError ? (
                                            <div className="text-red-500 text-center my-16">{videoError}</div>
                                        ) : (
                                            <video
                                                ref={videoRef}
                                                controls
                                                onError={handleVideoError}
                                                className="rounded shadow w-full max-w-[600px] max-h-[340px]"
                                            />
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
