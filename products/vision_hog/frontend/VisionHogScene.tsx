import { LemonTabs } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { someLogic } from './someLogic'
import { VideoStreamPlayer } from './VideoStreamPlayer'
import { VisionHogConfigScene } from './VisionHogConfigScene'

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
    const [currentTime, setCurrentTime] = React.useState(0)
    const [expanded, setExpanded] = React.useState<{ [idx: number]: boolean }>({})
    const toggleExpand = (idx: number): void => setExpanded((e) => ({ ...e, [idx]: !e[idx] }))
    const [activeTab, setActiveTab] = React.useState('video')

    // Show events whose time <= currentTime
    const visibleEvents = MOCK_EVENTS.filter((e) => e.time <= currentTime)

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
                                            <VideoStreamPlayer
                                                videoUrl={videoUrl}
                                                onTimeUpdate={setCurrentTime}
                                                className="w-full"
                                            />
                                        ) : (
                                            <div className="flex items-center justify-center h-[640px] w-full text-gray-500">
                                                Please save config to set video URL
                                            </div>
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
                                                        <span className="font-mono text-xs text-gray-500 mr-2">
                                                            {event.timestamp}
                                                        </span>
                                                        <span className="font-semibold">{event.event_name}</span>
                                                        <span className="ml-auto text-xs text-blue-700">
                                                            {expanded[idx] ? '▲' : '▼'}
                                                        </span>
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
