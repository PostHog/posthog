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

    // Gated on the media the list response already carried, so a page of observations without one costs
    // no requests. The URL is the endpoint rather than the asset, so a re-render after a retry still resolves.
    // Optional at runtime, whatever the generated type says: fixtures and a response cached from before
    // the field existed both reach here, and a poster must not take the scene down with it.
    const hasThumbnail = (observation.media ?? []).some((entry) =>
        chapter === undefined ? entry.kind === 'thumbnail' : entry.kind === 'chapter' && entry.position === chapter
    )
    const baseSrc =
        hasThumbnail && currentTeamId !== null && !failed
            ? getVisionObservationsThumbnailRetrieveUrl(String(currentTeamId), observation.id, { chapter, size })
            : undefined
    const src = baseSrc !== undefined && attempt > 0 ? `${baseSrc}&retry=${attempt}` : baseSrc
    const loaded = loadedSrc === src

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
                        loading="lazy"
                        decoding="async"
                        onLoad={() => setLoadedSrc(src)}
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
