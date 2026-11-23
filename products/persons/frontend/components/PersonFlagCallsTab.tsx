import { useActions, useMountedLogic, useValues } from 'kea'

import { FlagCallsList } from 'scenes/feature-flags/FlagCallsList'

import { personsLogic } from '../logics/personsLogic'

export function PersonFlagCallsTab(): JSX.Element {
    const mountedPersonsLogic = useMountedLogic(personsLogic)
    const { flagCallsQuery, flagCallsReachPastRetention } = useValues(mountedPersonsLogic)
    const { setFlagCallsQuery } = useActions(mountedPersonsLogic)

    return (
        <FlagCallsList
            uniqueKey="person-profile-flag-calls"
            attachTo={mountedPersonsLogic}
            query={flagCallsQuery}
            setQuery={setFlagCallsQuery}
            reachesPastRetention={flagCallsReachPastRetention}
        />
    )
}
