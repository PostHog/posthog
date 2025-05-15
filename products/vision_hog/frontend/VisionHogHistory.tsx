import { IconPauseFilled, IconPlayFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { useRef, useState } from 'react'
import { LemonEventName } from 'scenes/actions/EventName'

import { visionHogHistoryLogic } from './visionHogHistoryLogic'

const columns: LemonTableColumns<any> = [
    {
        title: 'Event',
        key: 'event',
        className: 'max-w-80',
        render: function Render(_, event) {
            return <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} />
        },
    },
    {
        title: 'Time',
        key: 'timestamp',
        className: 'max-w-80',
        render: function Render(_, event) {
            return <TZLabel time={event.timestamp} />
        },
    },
]

export function VisionHogHistory(): JSX.Element {
    const { events, filters } = useValues(visionHogHistoryLogic)
    const { setFilters } = useActions(visionHogHistoryLogic)

    // Video player state
    const videoRef = useRef<HTMLVideoElement>(null)
    const [isPlaying, setIsPlaying] = useState(false)
    const [currentTime, setCurrentTime] = useState(0)
    const [duration, setDuration] = useState(0)
    const [selectedEvent, setSelectedEvent] = useState<any>(null)

    // Handle play/pause
    const togglePlay = (): void => {
        if (!videoRef.current) {
            return
        }

        if (isPlaying) {
            videoRef.current.pause()
        } else {
            void videoRef.current.play()
        }
        setIsPlaying(!isPlaying)
    }

    // Handle time update
    const handleTimeUpdate = (): void => {
        if (!videoRef.current) {
            return
        }
        setCurrentTime(videoRef.current.currentTime)
    }

    // Handle seeking
    const handleSeek = (value: number): void => {
        if (!videoRef.current) {
            return
        }
        videoRef.current.currentTime = value
        setCurrentTime(value)
    }

    // Handle video metadata loaded
    const handleLoadedMetadata = (): void => {
        if (!videoRef.current) {
            return
        }
        setDuration(videoRef.current.duration)
    }

    // Format time in MM:SS
    const formatTime = (timeInSeconds: number): string => {
        const minutes = Math.floor(timeInSeconds / 60)
        const seconds = Math.floor(timeInSeconds % 60)
        return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    }

    // Handle row click to select video
    const handleRowClick = (record: any): void => {
        setSelectedEvent(record)
        // If the event has a video URL, set it to the video player
        if (record.properties?.video_url) {
            if (videoRef.current) {
                videoRef.current.src = record.properties.video_url
                setIsPlaying(false)
                setCurrentTime(0)
            }
        } else if (videoRef.current) {
            videoRef.current.src = 'https://videos.pexels.com/video-files/31365757/13384436_3240_2160_24fps.mp4'
            setIsPlaying(false)
            setCurrentTime(0)
        }
    }

    return (
        <div className="flex flex-col gap-4">
            {/* Video Player Section */}
            <div className="bg-bg-light rounded p-4 border">
                <h2 className="text-lg font-semibold mb-2">Event Recording</h2>
                <div className="flex flex-col gap-4">
                    <div className="relative w-full aspect-video bg-black rounded overflow-hidden">
                        {selectedEvent ? (
                            <video
                                ref={videoRef}
                                className="w-full h-full object-contain"
                                onTimeUpdate={handleTimeUpdate}
                                onLoadedMetadata={handleLoadedMetadata}
                                onEnded={() => setIsPlaying(false)}
                            />
                        ) : (
                            <div className="flex items-center justify-center h-full text-muted">
                                Select an event to view its recording
                            </div>
                        )}
                    </div>

                    {/* Video Controls */}
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-2">
                            <LemonButton
                                icon={isPlaying ? <IconPauseFilled /> : <IconPlayFilled />}
                                type="secondary"
                                size="small"
                                onClick={togglePlay}
                                disabled={!selectedEvent}
                            >
                                {isPlaying ? 'Pause' : 'Play'}
                            </LemonButton>
                            <span className="text-sm text-muted">
                                {formatTime(currentTime)} / {formatTime(duration)}
                            </span>
                        </div>

                        <LemonSlider
                            value={currentTime}
                            onChange={handleSeek}
                            min={0}
                            max={duration || 100}
                            step={0.1}
                        />
                    </div>
                </div>
            </div>

            {/* Events Table Section */}
            <div className="flex justify-end">
                <LemonEventName
                    value={filters.eventType}
                    onChange={(value) => setFilters({ ...filters, eventType: value })}
                    placeholder="Filter by event"
                    allEventsOption="clear"
                />
            </div>
            <LemonTable
                columns={columns}
                dataSource={events}
                rowKey="uuid"
                useURLForSorting={false}
                onRow={(record) => ({
                    onClick: () => handleRowClick(record),
                    className: selectedEvent?.uuid === record.uuid ? 'bg-primary-highlight' : '',
                })}
                emptyState={
                    <div className="flex flex-col justify-center items-center gap-4 p-6">
                        <span className="text-lg font-title font-semibold leading-tight">No events found</span>
                    </div>
                }
                nouns={['event', 'events']}
            />

            {/* Button to trigger handleRowClick */}
            <div className="flex justify-center mt-4">
                <LemonButton
                    type="primary"
                    onClick={() =>
                        handleRowClick({
                            uuid: 'demo-video',
                            properties: {},
                        })
                    }
                >
                    Load Demo Video
                </LemonButton>
            </div>
        </div>
    )
}
