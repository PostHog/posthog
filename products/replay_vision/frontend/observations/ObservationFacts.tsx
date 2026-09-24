import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { ObservationConfidence, ObservationStatusTag, readResult } from '../components/ObservationCard'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { OBSERVATION_TRIGGER_TAG } from '../replay_scanners/types'
import { hasScannerPage, scannerLabel } from '../utils/observation'
import { Fact, FactList } from './FactList'

export function ObservationFacts({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    const result = readResult(observation)
    const person = observation.recording_subject_email ?? observation.distinct_id

    return (
        <FactList>
            <Fact label="Person">
                {observation.distinct_id ? (
                    <Link to={urls.personByDistinctId(observation.distinct_id)} className="block truncate">
                        {person}
                    </Link>
                ) : (
                    <span className="text-muted">Unknown person</span>
                )}
            </Fact>
            <Fact label="Scanned">
                <TZLabel time={observation.created_at} />
            </Fact>
            <Fact label="Status">
                <ObservationStatusTag status={observation.status} errorReason={observation.error_reason} />
            </Fact>
            <Fact label="Triggered by">
                {observation.triggered_by !== 'schedule' && observation.triggered_by_user ? (
                    <ProfilePicture
                        user={{
                            first_name: observation.triggered_by_user.first_name,
                            last_name: observation.triggered_by_user.last_name,
                            email: observation.triggered_by_user.email,
                        }}
                        size="xs"
                        showName
                    />
                ) : (
                    OBSERVATION_TRIGGER_TAG[observation.triggered_by].label
                )}
            </Fact>
            {result && typeof result.confidence === 'number' && (
                <Fact label="Confidence">
                    <ObservationConfidence result={result} />
                </Fact>
            )}
            <Fact label="Scanner">
                {hasScannerPage(observation) ? (
                    <Link
                        to={urls.replayVision(observation.scanner_id)}
                        className="block truncate"
                        data-attr="vision-observation-scanner-link"
                    >
                        {scannerLabel(observation)}
                    </Link>
                ) : (
                    scannerLabel(observation)
                )}
            </Fact>
        </FactList>
    )
}
