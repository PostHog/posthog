import { useActions, useValues } from 'kea'

import { ChangeRequestBanner } from 'scenes/approvals/ChangeRequestBanner'
import { changeRequestsLogic } from 'scenes/approvals/changeRequestsLogic'
import { ApprovalResourceType } from 'scenes/approvals/utils'

import { Experiment } from '~/types'

import { openChangeRequestsForCurrentRun } from 'products/experiments/frontend/experimentActions'

/** One banner per open change request on the experiment, leaving out requests from an earlier run. */
export function ExperimentPendingChangeRequestBanners({
    experiment,
}: {
    experiment: Pick<Experiment, 'id' | 'start_date' | 'end_date'>
}): JSX.Element | null {
    const logic = changeRequestsLogic({ resourceType: ApprovalResourceType.EXPERIMENT, resourceId: experiment.id })
    const { changeRequests, actionInFlight } = useValues(logic)
    const { approveRequest, rejectRequest, cancelRequest } = useActions(logic)

    const openRequests = openChangeRequestsForCurrentRun(changeRequests, experiment)
    if (openRequests.length === 0) {
        return null
    }

    return (
        <>
            {openRequests.map((changeRequest) => (
                <ChangeRequestBanner
                    key={changeRequest.id}
                    changeRequest={changeRequest}
                    context="experiment"
                    onApprove={(id) => approveRequest(id)}
                    onReject={(id, reason) => rejectRequest(id, reason)}
                    onCancel={(id, reason) => cancelRequest(id, reason)}
                    actionInFlight={actionInFlight?.id === changeRequest.id ? actionInFlight.action : null}
                />
            ))}
        </>
    )
}
