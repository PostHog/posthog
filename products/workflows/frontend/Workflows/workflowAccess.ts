import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { HogFlow } from './hogflows/types'

// A workflow with no access level came from a list the backend did not annotate, so it stays editable.
export function canEditWorkflow(workflow: HogFlow | null, userAccessLevel: AccessControlLevel | null): boolean {
    return (
        workflow?.status !== 'archived' &&
        (!userAccessLevel ||
            accessLevelSatisfied(AccessControlResourceType.Workflow, userAccessLevel, AccessControlLevel.Editor))
    )
}
