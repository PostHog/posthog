import { useMountedLogic } from 'kea'

import type { Experiment } from '~/types'

import { experimentExposuresWindowLogic } from './experimentExposuresWindowLogic'

export function ExperimentExposuresWindowSync({ experiment }: { experiment: Experiment }): null {
    useMountedLogic(experimentExposuresWindowLogic({ experiment }))
    return null
}
