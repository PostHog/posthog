import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'

import { ActivityScope } from '~/types'

import { WorkflowRevisions } from '../Workflows/WorkflowRevisions'

export function BroadcastHistory({ id }: { id: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            {/* Restoring opens a draft in the workflow editor, which a sent broadcast must not offer. */}
            <WorkflowRevisions id={id} readOnly />
            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Activity</h3>
                <ActivityLog id={id} scope={ActivityScope.HOG_FLOW} />
            </div>
        </div>
    )
}
