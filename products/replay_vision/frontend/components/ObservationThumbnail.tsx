import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconVideoCamera } from '@posthog/icons'

import { teamLogic } from 'scenes/teamLogic'

import { getVisionObservationsThumbnailRetrieveUrl } from '../generated/api'
import { ReplayObservationApi } from '../generated/api.schemas'

interface ObservationThumbnailProps {
    observation: ReplayObservationApi
    /** Sizing and shape come from the caller, since a table cell and a detail page want very different frames. */
    className?: string
    children?: React.ReactNode
}

const RETRY_DELAY_MS = 2000

/** The frame the scan picked out of the session, as a 16:9 poster. */
export function ObservationThumbnail({ observation, className, children }: ObservationThumbnailProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [attempt, setAttempt] = useState(0)
    const [failedId, setFailedId] = useState<string | null>(null)
    const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

    // A row's instance is reused as the table pages, so a failure can outlive the observation it was for.
    useEffect(() => {
        setAttempt(0)
        setFailedId(null)
    }, [observation.id])

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
    const hasThumbnail = (observation.media ?? []).some((entry) => entry.kind === 'thumbnail')
    const baseSrc =
        hasThumbnail && currentTeamId !== null && !failed
            ? getVisionObservationsThumbnailRetrieveUrl(String(currentTeamId), observation.id)
            : undefined
    const src = baseSrc !== undefined && attempt > 0 ? `${baseSrc}?retry=${attempt}` : baseSrc

    const onError = (): void => {
        // One retry: the redirect target can blink, and the poster would stay blank for the whole mount.
        if (attempt === 0) {
            retryTimer.current = setTimeout(() => setAttempt(1), RETRY_DELAY_MS)
            return
        }
        setFailedId(observation.id)
    }

    return (
        <div className={`relative aspect-video overflow-hidden rounded border bg-surface-secondary ${className ?? ''}`}>
            {src && (
                <img
                    src={src}
                    alt=""
                    className="absolute inset-0 size-full object-cover"
                    loading="lazy"
                    decoding="async"
                    onError={onError}
                />
            )}
            <div className="absolute inset-0 flex items-center justify-center">
                {children ?? (!src && <IconVideoCamera className="text-xl text-tertiary" aria-hidden />)}
            </div>
        </div>
    )
}
