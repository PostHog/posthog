import { useValues } from 'kea'

import { experimentFlagCalledReferences } from 'lib/components/FlagCalledRebuildBanner/flagCalledDependencies'
import { FlagCalledRebuildBanner } from 'lib/components/FlagCalledRebuildBanner/FlagCalledRebuildBanner'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

export function ExperimentFlagCalledBanner(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    return (
        <FlagCalledRebuildBanner
            artifactType="experiment"
            references={experimentFlagCalledReferences(experiment)}
            className="mb-4"
        >
            This experiment's exposure criteria use Feature flag called through an action or an activation event, so it
            won't count exposures made after your organization's flag calls move out of the events table. Reach a
            decision with the exposures counted up to then, or launch a new experiment whose exposure criteria don't use
            Feature flag called.
        </FlagCalledRebuildBanner>
    )
}
