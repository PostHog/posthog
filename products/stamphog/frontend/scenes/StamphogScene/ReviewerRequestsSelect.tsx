import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import {
    OwnersFileStatusEnumApi,
    RoutingModeEnumApi,
    type CodeReviewApprovalRepositoryApi,
} from '../../generated/api.schemas'
import { ROUTING_MODE_LABELS } from '../../routingModeLabels'
import { managerDisabledReason } from './repoAccess'
import { stamphogSceneLogic } from './stamphogSceneLogic'

const ROUTING_MODE_OPTIONS = [RoutingModeEnumApi.Off, RoutingModeEnumApi.Fallback, RoutingModeEnumApi.Always].map(
    (value) => ({ value, label: ROUTING_MODE_LABELS[value] })
)

/** Whether auto-approval asks the code owners in owners.yaml to review, and when. */
export function ReviewerRequestsSelect({ repo }: { repo: CodeReviewApprovalRepositoryApi }): JSX.Element {
    const { updatingRepoIds, ownersFileChecks } = useValues(stamphogSceneLogic)
    const { updateRepoConfig } = useActions(stamphogSceneLogic)
    const mode = repo.routing_mode ?? RoutingModeEnumApi.Off
    // Requests read every owner from owners.yaml, so a repository known to have none is not offered them.
    // A repository that has them on keeps the select usable, so it can be turned off.
    const missingOwnersFile =
        mode === RoutingModeEnumApi.Off && ownersFileChecks[repo.id] === OwnersFileStatusEnumApi.Missing
            ? 'Add an owners.yaml to the default branch first'
            : undefined
    // Turning requests on asks teams on every pull request, and turning them off can leave pull requests
    // with no reviewer, so both directions take manager.
    const disabledReason =
        managerDisabledReason(toAccessControlLevel(repo.user_access_level)) ??
        missingOwnersFile ??
        (updatingRepoIds.includes(repo.id) ? 'Saving…' : undefined)

    return (
        <LemonSelect
            size="small"
            aria-label={`Reviewer requests for ${repo.repository}`}
            value={mode}
            options={ROUTING_MODE_OPTIONS}
            onChange={(routingMode) => updateRepoConfig(repo.id, { routing_mode: routingMode })}
            disabledReason={disabledReason}
            data-attr="stamphog-repo-reviewer-requests-mode"
        />
    )
}
