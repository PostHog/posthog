import clsx from 'clsx'
import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconVideoCamera } from '@posthog/icons'
import { Skeleton } from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { ReplayObservationApi, VisionObservationsThumbnailRetrieveSize } from '../generated/api.schemas'
import { observationThumbnailSrc } from './ObservationThumbnail'

const RETRY_DELAY_MS = 2000

/** Just under the endpoint's redirect cache, after which a remount refetches the poster. */
const DECODED_TTL_MS = 9 * 60 * 1000

const decodedThumbnails = new Map<string, number>()

function isDecoded(src: string): boolean {
    const decodedAt = decodedThumbnails.get(src)
    if (decodedAt !== undefined && Date.now() - decodedAt < DECODED_TTL_MS) {
        return true
    }
    decodedThumbnails.delete(src)
    return false
}

/** The frame the scan picked out of the session, as a 16:9 poster. */
export function QuillObservationThumbnail({
    observation,
    chapter,
    className,
    size = VisionObservationsThumbnailRetrieveSize.Large,
    retryKey,
    children,
}: {
    observation: ReplayObservationApi
    chapter?: number
    className?: string
    size?: VisionObservationsThumbnailRetrieveSize
    /** A new value clears a failed load, so a caller that keeps the poster mounted across data reloads can retry it. */
    retryKey?: unknown
    children?: React.ReactNode
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [attempt, setAttempt] = useState(0)
    const [failedId, setFailedId] = useState<string | null>(null)
    const [loadedSrc, setLoadedSrc] = useState<string | null>(null)
    const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

    // A row's instance is reused as the table pages, so a failure can outlive the observation it was for.
    useEffect(() => {
        setAttempt(0)
        setFailedId(null)
    }, [observation.id, chapter, retryKey])

    useEffect(() => {
        return () => {
            if (retryTimer.current !== null) {
                clearTimeout(retryTimer.current)
            }
        }
    }, [])

    const failed = failedId === observation.id
    const baseSrc = failed ? undefined : observationThumbnailSrc(currentTeamId, observation, { chapter, size })
    const src = baseSrc !== undefined && attempt > 0 ? `${baseSrc}&retry=${attempt}` : baseSrc
    const loaded = src !== undefined && (loadedSrc === src || isDecoded(src))

    const onError = (): void => {
        // One retry: the redirect target can blink, and the poster would stay blank for the whole mount.
        if (attempt === 0) {
            retryTimer.current = setTimeout(() => setAttempt(1), RETRY_DELAY_MS)
            return
        }
        setFailedId(observation.id)
    }

    return (
        <div className={clsx('relative aspect-video overflow-hidden rounded border border-border bg-muted', className)}>
            {src && (
                <>
                    {!loaded && <Skeleton className="absolute inset-0 size-full rounded-none" />}
                    <img
                        src={src}
                        alt=""
                        className={clsx(
                            'absolute inset-0 size-full object-cover transition-opacity duration-300 motion-reduce:transition-none',
                            loaded ? 'opacity-100' : 'opacity-0'
                        )}
                        loading={loaded ? 'eager' : 'lazy'}
                        decoding="async"
                        onLoad={() => {
                            decodedThumbnails.set(src, Date.now())
                            setLoadedSrc(src)
                        }}
                        onError={onError}
                    />
                </>
            )}
            <div className="absolute inset-0 flex items-center justify-center">
                {children ?? (!src && <IconVideoCamera className="text-xl text-muted-foreground" aria-hidden />)}
            </div>
        </div>
    )
}
