import flvjs from 'flv.js'
import Hls from 'hls.js'
import React from 'react'

export interface VideoStreamPlayerProps {
    videoUrl: string
    onTimeUpdate?: (currentTime: number) => void
    className?: string
}

const BUFFER_LENGTH = 0
const MAX_RETRIES = 3
const RETRY_DELAY_MS = 2000

export const VideoStreamPlayer: React.FC<VideoStreamPlayerProps> = ({ videoUrl, onTimeUpdate, className }) => {
    const videoRef = React.useRef<HTMLVideoElement>(null)
    const playerRef = React.useRef<flvjs.Player | null>(null)
    const [videoError, setVideoError] = React.useState<string | null>(null)
    const retryCountRef = React.useRef(0)

    const cleanupPlayer = React.useCallback(() => {
        if (playerRef.current) {
            try {
                playerRef.current.destroy()
            } catch (e) {
                // Ignore destroy errors
            }
            playerRef.current = null
        }
    }, [])

    const createPlayer = React.useCallback(() => {
        if (!videoRef.current || !videoUrl) {
            return null
        }

        const player = flvjs.createPlayer(
            {
                type: 'flv',
                url: videoUrl,
                isLive: true,
            },
            {
                enableStashBuffer: true,
                stashInitialSize: BUFFER_LENGTH,
            }
        )

        player.attachMediaElement(videoRef.current)
        player.load()
        const playPromise = player.play()
        if (playPromise !== undefined) {
            playPromise.catch(() => {
                // Ignore play() promise rejection - browser might block autoplay
            })
        }

        return player
    }, [videoUrl])

    React.useEffect(() => {
        setVideoError(null)
        retryCountRef.current = 0
        if (videoUrl && videoRef.current) {
            videoRef.current.src = ''
            if (Hls.isSupported() && videoUrl.endsWith('.m3u8')) {
                const hls = new Hls({ maxBufferLength: BUFFER_LENGTH })
                hls.loadSource(videoUrl)
                hls.attachMedia(videoRef.current)
                hls.on(Hls.Events.ERROR, () => setVideoError('Could not load video stream.'))
                return () => hls.destroy()
            } else if (flvjs.isSupported() && videoUrl.endsWith('.flv')) {
                cleanupPlayer()
                const player = createPlayer()
                if (!player) {
                    return
                }

                playerRef.current = player

                const errorHandler = (): void => {
                    if (retryCountRef.current < MAX_RETRIES) {
                        retryCountRef.current++
                        setTimeout(() => {
                            cleanupPlayer()
                            const newPlayer = createPlayer()
                            if (newPlayer) {
                                playerRef.current = newPlayer
                                newPlayer.on(flvjs.Events.ERROR, errorHandler)
                                newPlayer.on(flvjs.Events.LOADING_COMPLETE, () => {
                                    retryCountRef.current = 0
                                    const playPromise = newPlayer.play()
                                    if (playPromise !== undefined) {
                                        playPromise.catch(() => {
                                            // Ignore play() promise rejection - browser might block autoplay
                                        })
                                    }
                                })
                            }
                        }, RETRY_DELAY_MS)
                    } else {
                        setVideoError('Could not load video stream after multiple attempts.')
                    }
                }

                player.on(flvjs.Events.ERROR, errorHandler)
                player.on(flvjs.Events.LOADING_COMPLETE, () => {
                    retryCountRef.current = 0
                    const playPromise = player.play()
                    if (playPromise !== undefined) {
                        playPromise.catch(() => {
                            // Ignore play() promise rejection - browser might block autoplay
                        })
                    }
                })

                return () => {
                    cleanupPlayer()
                }
            }
            videoRef.current.src = videoUrl
        }
    }, [videoUrl, cleanupPlayer, createPlayer])

    React.useEffect(() => {
        const video = videoRef.current
        if (!video) {
            return
        }
        const handler = (): void => {
            onTimeUpdate?.(video.currentTime)
        }
        video.addEventListener('timeupdate', handler)
        return () => video.removeEventListener('timeupdate', handler)
    }, [videoUrl, onTimeUpdate])

    const handleVideoError = (): void => setVideoError('Could not load video stream.')

    return (
        <div className={className}>
            {!videoUrl ? (
                <div className="text-gray-500 text-center my-16">No video stream. Enter a valid URL above.</div>
            ) : videoError ? (
                <div className="text-red-500 text-center my-16">{videoError}</div>
            ) : (
                <video ref={videoRef} controls onError={handleVideoError} className="rounded shadow w-full" />
            )}
        </div>
    )
}
