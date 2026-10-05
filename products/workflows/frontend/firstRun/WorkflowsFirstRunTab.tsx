import { useValues } from 'kea'
import { router } from 'kea-router'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { workflowsSetupLogic } from '../emptyState/workflowsSetupLogic'
import { WorkflowsTable } from '../Workflows/WorkflowsTable'
import { FIRST_RUN_TEMPLATE_PARAM } from './firstRunGalleryLogic'
import { WorkflowsFirstRunGallery } from './WorkflowsFirstRunGallery'
import { WorkflowsFirstRunMakeItYours } from './WorkflowsFirstRunMakeItYours'

export function WorkflowsFirstRunTab(): JSX.Element {
    const { setupStatus } = useValues(workflowsSetupLogic)
    const { searchParams } = useValues(router)
    const pickedTemplateId = searchParams[FIRST_RUN_TEMPLATE_PARAM]

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
