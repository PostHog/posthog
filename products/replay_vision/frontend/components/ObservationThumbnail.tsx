import clsx from 'clsx'
import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconVideoCamera } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { getVisionObservationsThumbnailRetrieveUrl } from '../generated/api'
import { ReplayObservationApi, VisionObservationsThumbnailRetrieveSize } from '../generated/api.schemas'

interface ObservationThumbnailProps {
    observation: ReplayObservationApi
    /** A summary chapter's index, to show that chapter's frame instead of the observation's thumbnail. */
    chapter?: number
    /** Sizing and shape come from the caller, since a table cell and a detail page want very different frames. */
    className?: string
    /** `small` (up to 480px wide) for posters at most 240px wide, so it stays sharp at 2x. Defaults to `large`. */
    size?: VisionObservationsThumbnailRetrieveSize
    /** A new value clears a failed load, so a caller that keeps the poster mounted across data reloads can retry it. */
    retryKey?: unknown
    children?: React.ReactNode
}

const RETRY_DELAY_MS = 2000

/** Just under the endpoint's redirect cache, after which a remount refetches the poster. */
const DECODED_TTL_MS = 9 * 60 * 1000

const decodedThumbnails = new Map<string, number>()

const thumbnailPreloads = new Map<string, Promise<void>>()

function isDecoded(src: string): boolean {
    const decodedAt = decodedThumbnails.get(src)
    if (decodedAt === undefined) {
        return false
    }
    if (Date.now() - decodedAt < DECODED_TTL_MS) {
        return true
    }
    decodedThumbnails.delete(src)
    thumbnailPreloads.delete(src)
    return false
}

/** Downloads and decodes a poster ahead of its card, once per URL, and resolves even when the load fails. */
export function preloadObservationThumbnail(src: string): Promise<void> {
    isDecoded(src) // Drops an expired entry, so the preload below fetches again.
    let preload = thumbnailPreloads.get(src)
    if (!preload) {
        const image = new Image()
        image.src = src
        preload = image
            .decode()
            .then(() => {
                decodedThumbnails.set(src, Date.now())
            })
            .catch(() => undefined)
        thumbnailPreloads.set(src, preload)
    }
    return preload
}

export function observationThumbnailSrc(
    teamId: number | null,
    observation: ReplayObservationApi,
    {
        chapter,
        size = VisionObservationsThumbnailRetrieveSize.Large,
    }: { chapter?: number; size?: VisionObservationsThumbnailRetrieveSize } = {}
): string | undefined {
    // Gated on the media the list response already carried, so a page of observations without one costs
    // no requests. The URL is the endpoint rather than the asset, so a re-render after a retry still resolves.
    // Optional at runtime, whatever the generated type says: fixtures and a response cached from before
    // the field existed both reach here, and a poster must not take the scene down with it.
    const hasThumbnail = (observation.media ?? []).some((entry) =>
        chapter === undefined ? entry.kind === 'thumbnail' : entry.kind === 'chapter' && entry.position === chapter
    )
    return hasThumbnail && teamId !== null
        ? getVisionObservationsThumbnailRetrieveUrl(String(teamId), observation.id, { chapter, size })
        : undefined
}

/** The frame the scan picked out of the session, as a 16:9 poster. */
export function ObservationThumbnail({
    observation,
    chapter,
    className,
    size = VisionObservationsThumbnailRetrieveSize.Large,
    retryKey,
    children,
}: ObservationThumbnailProps): JSX.Element {
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
        <div className={clsx('relative aspect-video overflow-hidden rounded border bg-surface-secondary', className)}>
            {src && (
                <>
                    {!loaded && <LemonSkeleton className="absolute inset-0 size-full rounded-none" />}
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
                {children ?? (!src && <IconVideoCamera className="text-xl text-tertiary" aria-hidden />)}
            </div>
        </div>
    )
}
