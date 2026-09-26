import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { WorkflowsReputation } from './WorkflowsReputation'
import { WorkflowsReputationActions } from './WorkflowsReputationActions'

// The two pages share no components or logic, so removing the flag deletes one branch whole.
export function ReputationTab(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.WORKFLOWS_REPUTATION_ACTION_LIST] ? (
        <WorkflowsReputationActions />
    ) : (
        <WorkflowsReputation />
    )
}
