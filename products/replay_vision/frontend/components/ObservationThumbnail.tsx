import { useValues } from 'kea'
import { useState } from 'react'

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

/** The frame the scan picked out of the session, as a 16:9 poster. */
export function ObservationThumbnail({ observation, className, children }: ObservationThumbnailProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [failed, setFailed] = useState(false)

    // Gated on the media the list response already carried, so a page of observations without one costs
    // no requests. The URL is the endpoint rather than the asset, so a re-render after a retry still resolves.
    const hasThumbnail = observation.media.some((entry) => entry.kind === 'thumbnail')
    const src =
        hasThumbnail && currentTeamId !== null && !failed
            ? getVisionObservationsThumbnailRetrieveUrl(String(currentTeamId), observation.id)
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
            <div className="absolute inset-0 flex items-center justify-center">
                {children ?? (!src && <IconVideoCamera className="text-xl text-tertiary" aria-hidden />)}
            </div>
        </div>
    )
}
