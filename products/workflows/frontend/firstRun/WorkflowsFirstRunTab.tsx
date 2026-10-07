import { useMountedLogic, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { workflowsSetupLogic } from '../emptyState/workflowsSetupLogic'
import { WorkflowsTable } from '../Workflows/WorkflowsTable'
import { firstRunWelcomeHoldLogic } from './firstRunWelcomeHoldLogic'
import { WorkflowsFirstRunGallery } from './WorkflowsFirstRunGallery'

export function WorkflowsFirstRunTab(): JSX.Element {
    const { setupStatus } = useValues(workflowsSetupLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    useMountedLogic(firstRunWelcomeHoldLogic({ setupStatus }))

    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]) {
        return <WorkflowsTable />
    }

    if (setupStatus === 'loading') {
        return (
            <div className="flex justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }
    return setupStatus === 'needs-setup' ? <WorkflowsFirstRunGallery /> : <WorkflowsTable />
}
