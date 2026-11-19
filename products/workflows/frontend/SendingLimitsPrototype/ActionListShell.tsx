// PROTOTYPE (branch prototype/sending-limits-ux): mounts the action-list Reputation tab from the
// feat/workflows-reputation-action-inbox branch with fake data, never merge.
import { useActions, useMountedLogic } from 'kea'
import { ReactNode, useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { reputationResponseLogic } from './ActionList/reputationResponseLogic'
import { WorkflowsReputationActions } from './ActionList/WorkflowsReputationActions'
import { reputationResponseFor } from './ReputationShell'
import { SendingState } from './sendingLimitsPrototypeData'

let currentResponse: TeamEmailReputationResponseApi | null = null

interface ActionListShellProps {
    renderKey: string
    state: SendingState
    top: ReactNode
}

export function ActionListShell({ renderKey, state, top }: ActionListShellProps): JSX.Element {
    currentResponse = reputationResponseFor(state)
    useStorybookMocks({ get: { '/api/projects/:team_id/hog_flows/reputation': () => [200, currentResponse] } })
    useMountedLogic(reputationResponseLogic)
    const { loadReputationSuccess } = useActions(reputationResponseLogic)
    useEffect(() => {
        loadReputationSuccess(reputationResponseFor(state))
    }, [renderKey]) // eslint-disable-line react-hooks/exhaustive-deps
    return <WorkflowsReputationActions key={renderKey} top={top} />
}
