import { useMountedLogic, useValues } from 'kea'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { workflowsSetupLogic } from '../emptyState/workflowsSetupLogic'
import { WorkflowsTable } from '../Workflows/WorkflowsTable'
import { WorkflowsFirstRunGallery } from './WorkflowsFirstRunGallery'

export function WorkflowsFirstRunTab(): JSX.Element {
    useMountedLogic(workflowsSetupLogic)
    const { setupStatus } = useValues(workflowsSetupLogic)

    if (setupStatus === 'loading') {
        return (
            <div className="flex justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }
    return setupStatus === 'needs-setup' ? <WorkflowsFirstRunGallery /> : <WorkflowsTable />
}
