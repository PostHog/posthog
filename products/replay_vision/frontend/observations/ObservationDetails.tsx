import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { formatDurationMilliseconds } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { modelLabel, modelNamingVariant } from '../replay_scanners/types'
import { Fact, FactList } from './FactList'

function durationLabel(observation: ReplayObservationApi): string | null {
    if (!observation.started_at || !observation.completed_at) {
        return null
    }
    const ms = dayjs(observation.completed_at).diff(observation.started_at)
    return Number.isFinite(ms) && ms >= 0 ? formatDurationMilliseconds(ms) : null
}

export function ObservationDetails({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const snapshot = observation.scanner_snapshot
    const { featureFlags } = useValues(featureFlagLogic)
    const namingVariant = modelNamingVariant(featureFlags[FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT])
    const duration = durationLabel(observation)

    return (
        <div className="flex flex-col gap-2">
            <button
                type="button"
                className="flex items-center gap-1 text-sm font-medium self-start hover:text-default"
                onClick={() => setExpanded(!expanded)}
                aria-expanded={expanded}
                data-attr="vision-observation-technical-details-toggle"
            >
                <IconChevronRight className={cn('transition-transform', expanded && 'rotate-90')} />
                Details
            </button>
            {expanded && (
                <FactList>
                    <Fact label="Observation ID">
                        <CopyToClipboardInline explicitValue={observation.id} iconSize="xsmall" className="min-w-0">
                            <span className="font-mono text-xs truncate">{observation.id}</span>
                        </CopyToClipboardInline>
                    </Fact>
                    <Fact label="Session">
                        <Link
                            to={urls.sessionProfile(observation.session_id)}
                            className="block font-mono text-xs truncate"
                            data-attr="vision-observation-session-link"
                        >
                            {observation.session_id}
                        </Link>
                    </Fact>
                    {/* The backend emits the event only once a scan succeeds. */}
                    {observation.status === 'succeeded' && observation.completed_at && (
                        <Fact label="Observation event">
                            <Link to={urls.event(observation.id, observation.completed_at)}>$recording_observed</Link>
                        </Fact>
                    )}
                    {observation.started_at && (
                        <Fact label="Started">
                            <TZLabel time={observation.started_at} />
                        </Fact>
                    )}
                    {observation.completed_at && (
                        <Fact label="Completed">
                            <TZLabel time={observation.completed_at} />
                        </Fact>
                    )}
                    {duration && <Fact label="Duration">{duration}</Fact>}
                    {snapshot?.model && <Fact label="Model">{modelLabel(snapshot.model, namingVariant)}</Fact>}
                </FactList>
            )}
        </div>
    )
}
