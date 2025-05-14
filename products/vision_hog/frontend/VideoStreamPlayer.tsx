import flvjs from 'flv.js'
import Hls from 'hls.js'
import React from 'react'

export interface VideoStreamPlayerProps {
    videoUrl: string
    onTimeUpdate?: (currentTime: number) => void
    className?: string
}

export const VideoStreamPlayer: React.FC<VideoStreamPlayerProps> = ({ videoUrl, onTimeUpdate, className }) => {
    const videoRef = React.useRef<HTMLVideoElement>(null)
    const [videoError, setVideoError] = React.useState<string | null>(null)

    React.useEffect(() => {
        setVideoError(null)
        if (videoUrl && videoRef.current) {
            videoRef.current.src = ''
            if (Hls.isSupported() && videoUrl.endsWith('.m3u8')) {
                const hls = new Hls({ maxBufferLength: 0 })
                hls.loadSource(videoUrl)
                hls.attachMedia(videoRef.current)
                hls.on(Hls.Events.ERROR, () => setVideoError('Could not load video stream.'))
                return () => hls.destroy()
            } else if (flvjs.isSupported() && videoUrl.endsWith('.flv')) {
                const flvPlayer = flvjs.createPlayer(
                    {
                        type: 'flv',
                        url: videoUrl,
                        isLive: true,
                    },
                    {
                        enableStashBuffer: true,
                        stashInitialSize: 0,
                    }
                )
                flvPlayer.attachMediaElement(videoRef.current)
                flvPlayer.load()
                void flvPlayer.play()
                flvPlayer.on(flvjs.Events.ERROR, () => setVideoError('Could not load video stream.'))
                return () => flvPlayer.destroy()
            }
            videoRef.current.src = videoUrl
        }
    }, [videoUrl])

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
                <video
                    ref={videoRef}
                    controls
                    onError={handleVideoError}
                    className="rounded shadow w-full max-w-[600px] max-h-[340px]"
                />
            )}
        </div>
    )
}
