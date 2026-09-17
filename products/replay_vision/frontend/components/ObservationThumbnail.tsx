import { useValues } from 'kea'
import { useState } from 'react'

import { IconVideoCamera } from '@posthog/icons'

import { teamLogic } from 'scenes/teamLogic'

import { getVisionObservationsThumbnailRetrieveUrl } from '../generated/api'

interface ObservationThumbnailProps {
    observationId: string
    /** Sizing and shape come from the caller, since a table cell and a detail page want very different frames. */
    className?: string
    children?: React.ReactNode
}

/** The frame the scan picked out of the session, as a 16:9 poster. */
export function ObservationThumbnail({ observationId, className, children }: ObservationThumbnailProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [failed, setFailed] = useState(false)

    // The endpoint 404s until the media render lands, which is also how an expired object reads.
    const src =
        currentTeamId !== null && !failed
            ? getVisionObservationsThumbnailRetrieveUrl(String(currentTeamId), observationId)
            : undefined

    return (
        <div className={`relative aspect-video overflow-hidden rounded border bg-surface-secondary ${className ?? ''}`}>
            {src && (
                <img
                    src={src}
                    alt=""
                    className="absolute inset-0 size-full object-cover"
                    loading="lazy"
                    decoding="async"
                    onError={() => setFailed(true)}
                />
            )}
            {!src && !children && (
                <div className="absolute inset-0 flex items-center justify-center">
                    <IconVideoCamera className="text-xl text-tertiary" aria-hidden />
                </div>
            )}
            {children && <div className="absolute inset-0 flex items-center justify-center">{children}</div>}
        </div>
    )
}
