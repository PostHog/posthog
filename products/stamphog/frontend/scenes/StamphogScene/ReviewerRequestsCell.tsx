import { useActions, useValues } from 'kea'

import { LemonSelect, Link } from '@posthog/lemon-ui'

import { StateDot } from 'lib/components/RepositoryList/StateDot'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import {
    OwnersFileStatusEnumApi,
    RoutingModeEnumApi,
    type CodeReviewApprovalRepositoryApi,
} from '../../generated/api.schemas'
import { ROUTING_MODE_LABELS } from '../../routingModeLabels'
import { managerDisabledReason } from './repoAccess'
import { type OwnersFileCheck, stamphogSceneLogic } from './stamphogSceneLogic'

const ROUTING_MODE_OPTIONS = [RoutingModeEnumApi.Off, RoutingModeEnumApi.Fallback, RoutingModeEnumApi.Always].map(
    (value) => ({
        value,
        label: ROUTING_MODE_LABELS[value],
        icon: <StateDot state={value === RoutingModeEnumApi.Off ? 'off' : 'on'} />,
    })
)

const OWNERS_FOUND_HINT: Record<RoutingModeEnumApi, string> = {
    [RoutingModeEnumApi.Off]: 'owners.yaml found',
    [RoutingModeEnumApi.Fallback]: 'owners.yaml found · approved PRs ask only pinned owners',
    [RoutingModeEnumApi.Always]: 'owners.yaml found · every ready PR asks its owners',
}

function OwnersFileHint({
    repoId,
    mode,
    ownersFile,
}: {
    repoId: string
    mode: RoutingModeEnumApi
    ownersFile: OwnersFileCheck | undefined
}): JSX.Element | null {
    const { checkOwnersFile } = useActions(stamphogSceneLogic)

    switch (ownersFile) {
        case OwnersFileStatusEnumApi.Found:
            return <span data-attr="stamphog-owners-file-found">{OWNERS_FOUND_HINT[mode]}</span>
        case OwnersFileStatusEnumApi.Missing:
            return <span>no owners.yaml</span>
        case OwnersFileStatusEnumApi.Unavailable:
            return (
                <span>
                    Couldn't check for owners.yaml.{' '}
                    <Link onClick={() => checkOwnersFile(repoId)} data-attr="stamphog-owners-file-retry">
                        Try again
                    </Link>
                </span>
            )
        case 'checking':
            return <span>Checking for owners.yaml…</span>
        default:
            return null
    }
}

export function ReviewerRequestsCell({ repo }: { repo: CodeReviewApprovalRepositoryApi }): JSX.Element {
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
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <LemonSelect
                size="small"
                aria-label={`Reviewer requests for ${repo.repository}`}
                value={mode}
                options={ROUTING_MODE_OPTIONS}
                onChange={(routingMode) => updateRepoConfig(repo.id, { routing_mode: routingMode })}
                disabledReason={disabledReason}
                data-attr="stamphog-repo-reviewer-requests-mode"
            />
            <span className="text-xs text-secondary">
                <OwnersFileHint repoId={repo.id} mode={mode} ownersFile={ownersFileChecks[repo.id]} />
            </span>
        </div>
    )
}
