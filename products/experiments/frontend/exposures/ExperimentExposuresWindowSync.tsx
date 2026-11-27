import { useMountedLogic } from 'kea'

import type { Experiment } from '~/types'

import { experimentExposuresWindowLogic } from './experimentExposuresWindowLogic'

/** Keeps the exposures and the health on the window of the latest results run, whichever tab is open. */
export function ExperimentExposuresWindowSync({ experiment }: { experiment: Experiment }): null {
    useMountedLogic(experimentExposuresWindowLogic({ experiment }))
    return null
}
