import { useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { workflowsSetupLogic } from '../emptyState/workflowsSetupLogic'
import { WorkflowsTable } from '../Workflows/WorkflowsTable'
import { FIRST_RUN_TEMPLATE_PARAM } from './firstRunGalleryLogic'
import { firstRunWelcomeHoldLogic } from './firstRunWelcomeHoldLogic'
import { WorkflowsFirstRunGallery } from './WorkflowsFirstRunGallery'
import { WorkflowsFirstRunMakeItYours } from './WorkflowsFirstRunMakeItYours'

export function WorkflowsFirstRunTab(): JSX.Element {
    const { setupStatus } = useValues(workflowsSetupLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    useMountedLogic(firstRunWelcomeHoldLogic({ setupStatus }))
    const { searchParams } = useValues(router)
    const pickedTemplateId = searchParams[FIRST_RUN_TEMPLATE_PARAM]

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
    if (setupStatus !== 'needs-setup') {
        return <WorkflowsTable />
    }
    return typeof pickedTemplateId === 'string' ? (
        <WorkflowsFirstRunMakeItYours templateId={pickedTemplateId} />
    ) : (
        <WorkflowsFirstRunGallery />
    )
}
