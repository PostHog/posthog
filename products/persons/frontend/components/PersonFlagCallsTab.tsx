import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { FLAG_EVALUATIONS_RETENTION_DAYS } from 'scenes/feature-flags/flagEvaluationsTable'

import { Query } from '~/queries/Query/Query'

import { personsLogic } from '../logics/personsLogic'

const PERSON_FLAG_CALLS_KEY = 'person-profile-flag-calls'

export function PersonFlagCallsTab(): JSX.Element {
    const mountedPersonsLogic = useMountedLogic(personsLogic)
    const { flagCallsQuery, flagCallsReachPastRetention } = useValues(mountedPersonsLogic)
    const { setFlagCallsQuery } = useActions(mountedPersonsLogic)
    const queryLogicKey = `${PERSON_FLAG_CALLS_KEY}-${mountedPersonsLogic.key}`

    return (
        <>
            {flagCallsReachPastRetention && (
                <LemonBanner type="info" className="mb-2">
                    This list shows feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days.
                </LemonBanner>
            )}
            <Query
                uniqueKey={PERSON_FLAG_CALLS_KEY}
                attachTo={mountedPersonsLogic}
                query={flagCallsQuery}
                setQuery={(q) => setFlagCallsQuery(q)}
                context={{
                    insightProps: {
                        dashboardItemId: `new-${queryLogicKey}`,
                        dataNodeCollectionId: queryLogicKey,
                    },
                    emptyStateHeading: 'No feature flag calls',
                    emptyStateDetail: flagCallsReachPastRetention
                        ? `Flag calls are kept for ${FLAG_EVALUATIONS_RETENTION_DAYS} days.`
                        : 'Try widening the date range.',
                }}
            />
        </>
    )
}
