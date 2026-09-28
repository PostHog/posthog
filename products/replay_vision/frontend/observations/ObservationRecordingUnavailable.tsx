import { IconVideoCamera } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ObservationThumbnail } from '../components/ObservationThumbnail'
import type { ReplayObservationApi } from '../generated/api.schemas'

export function ObservationRecordingUnavailable({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    const hasFrame = observation.media.some((entry) => entry.kind === 'thumbnail')
    return (
        <div
            className="h-full flex flex-col items-center justify-center gap-4 p-6 text-center"
            data-attr="vision-observation-recording-unavailable"
        >
            {hasFrame ? (
                <figure className="m-0 flex flex-col items-center gap-2 w-full max-w-xl">
                    <ObservationThumbnail observation={observation} className="w-full" />
                    <figcaption className="text-xs text-muted">
                        The frame saved when this recording was scanned.
                    </figcaption>
                </figure>
            ) : (
                <IconVideoCamera className="text-4xl text-muted" />
            )}
            <div className="flex flex-col gap-1 max-w-md">
                <span className="text-base font-semibold">This recording is no longer available</span>
                <span className="text-sm text-secondary">
                    Recordings are deleted once they pass your project's retention period. The scan result stays, so you
                    can still read it and rate it.
                </span>
            </div>
            <Link
                to={urls.settings('project-replay', 'replay-retention')}
                target="_blank"
                targetBlankIcon
                className="text-sm"
            >
                Manage replay data retention
            </Link>
        </div>
    )
}
