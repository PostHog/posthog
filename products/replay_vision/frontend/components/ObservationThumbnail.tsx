import { useValues } from 'kea'
import { useState } from 'react'

import { IconVideoCamera } from '@posthog/icons'

import { teamLogic } from 'scenes/teamLogic'

import { getExportsContentRetrieveUrl } from '~/generated/core/api'

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

    const thumbnail = observation.media.find((entry) => entry.kind === 'thumbnail')
    const src =
        currentTeamId !== null && thumbnail && !failed
            ? getExportsContentRetrieveUrl(String(currentTeamId), thumbnail.asset_id)
            : undefined

    return (
        <div className={`relative aspect-video overflow-hidden rounded border bg-surface-secondary ${className ?? ''}`}>
            {src ? (
                <img
                    src={src}
                    alt={`Frame from session ${observation.session_id}`}
                    className="absolute inset-0 size-full object-cover"
                    loading="lazy"
                    decoding="async"
                    onError={() => setFailed(true)}
                />
            ) : (
                !children && (
                    <div className="absolute inset-0 flex items-center justify-center">
                        <IconVideoCamera className="text-xl text-tertiary" aria-hidden />
                    </div>
                )
            )}
            {children && <div className="absolute inset-0 flex items-center justify-center">{children}</div>}
        </div>
    )
}
