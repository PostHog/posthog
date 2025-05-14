import flvjs from 'flv.js'
import Hls from 'hls.js'
import { useActions, useValues } from 'kea'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'

// import { useActions, useValues } from 'kea' // Uncomment if you use actions/values from logic
import { someLogic } from './someLogic'

const VIDEO_BUFFER_SECONDS = 0

// Mock event data
const MOCK_EVENTS = [
    {
        time: 2,
        event_name: 'Start',
        timestamp: '00:02',
        description: 'The video starts.',
        details: { foo: 'bar', baz: 123 },
    },
    {
        time: 5,
        event_name: 'First Action',
        timestamp: '00:05',
        description: 'First action occurs.',
        details: { action: 'jump', value: 42 },
    },
    {
        time: 12,
        event_name: 'Climax',
        timestamp: '00:12',
        description: 'The big moment.',
        details: { excitement: 'high', score: 99 },
    },
    {
        time: 20,
        event_name: 'End',
        timestamp: '00:20',
        description: 'The video ends.',
        details: { result: 'success', duration: '20s' },
    },
]

export const scene: SceneExport = {
    component: VisionHogScene,
    logic: someLogic,
}

export function VisionHogScene(): JSX.Element {
    const { videoUrl } = useValues(someLogic)
    const { setVideoUrl } = useActions(someLogic)
    const videoRef = React.useRef<HTMLVideoElement>(null)
    const [videoError, setVideoError] = React.useState<string | null>(null)
    const [currentTime, setCurrentTime] = React.useState(0)
    const [expanded, setExpanded] = React.useState<{ [idx: number]: boolean }>({})
    const toggleExpand = (idx: number): void => setExpanded((e) => ({ ...e, [idx]: !e[idx] }))

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

    // Listen to video time updates
    React.useEffect(() => {
        const video = videoRef.current
        if (!video) {
            return
        }
        const handler = (): void => setCurrentTime(video.currentTime)
        video.addEventListener('timeupdate', handler)
        return () => video.removeEventListener('timeupdate', handler)
    }, [videoUrl])

    // Show events whose time <= currentTime
    const visibleEvents = MOCK_EVENTS.filter((e) => e.time <= currentTime)

    return (
        <div className="flex flex-row w-full max-w-5xl mx-auto mt-8 gap-8">
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
                        <div className="text-gray-500 text-center my-16">No video stream. Enter a valid URL above.</div>
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
                <h2 className="text-lg font-semibold mb-4">Events</h2>
                {visibleEvents.length === 0 ? (
                    <div className="text-gray-400">No events yet.</div>
                ) : (
                    <ul>
                        {visibleEvents.map((event, idx) => (
                            <li
                                key={idx}
                                className="mb-2 p-2 bg-blue-50 rounded shadow-sm cursor-pointer animate-fade-in"
                                onClick={() => toggleExpand(idx)}
                            >
                                <div className="flex items-center justify-between">
                                    <span className="font-mono text-xs text-gray-500 mr-2">{event.timestamp}</span>
                                    <span className="font-semibold">{event.event_name}</span>
                                    <span className="ml-auto text-xs text-blue-700">{expanded[idx] ? '▲' : '▼'}</span>
                                </div>
                                {expanded[idx] && (
                                    <div className="mt-2 text-sm text-gray-700">
                                        <div className="mb-1">{event.description}</div>
                                        <pre className="bg-blue-100 rounded p-2 text-xs overflow-x-auto">
                                            {JSON.stringify(event.details, null, 2)}
                                        </pre>
                                    </div>
                                )}
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    )
}
