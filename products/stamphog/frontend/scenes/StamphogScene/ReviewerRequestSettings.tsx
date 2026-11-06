import { useActions } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonSelect, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import { OwnersFileStatusEnumApi, RoutingModeEnumApi, type StamphogRepoConfigApi } from '../../generated/api.schemas'
import { ROUTING_MODE_LABELS } from '../../routingModeLabels'
import { managerDisabledReason } from './repoAccess'
import { type OwnersFileCheck, stamphogSceneLogic } from './stamphogSceneLogic'

function OwnersFileState({ ownersFile }: { ownersFile: OwnersFileCheck | undefined }): JSX.Element {
    switch (ownersFile) {
        case OwnersFileStatusEnumApi.Found:
            return (
                <span className="flex items-center gap-1 text-success text-sm" data-attr="stamphog-owners-file-found">
                    <IconCheckCircle />
                    owners.yaml found
                </span>
            )
        case OwnersFileStatusEnumApi.Missing:
            return (
                <span className="flex items-center gap-1 text-warning text-sm">
                    <IconWarning />
                    No owners.yaml on the default branch, so nobody gets a review request.
                </span>
            )
        case OwnersFileStatusEnumApi.Unavailable:
            return (
                <span className="text-secondary text-sm">Couldn't check for owners.yaml. Reopen the row to retry.</span>
            )
        default:
            return (
                <span className="flex items-center gap-1 text-secondary text-sm">
                    <Spinner />
                    Checking for owners.yaml
                </span>
            )
    }
}

export function ReviewerRequestSettings({
    repo,
    ownersFile,
    updatingReason,
}: {
    repo: StamphogRepoConfigApi
    ownersFile: OwnersFileCheck | undefined
    updatingReason?: string
}): JSX.Element {
    const { updateRepoConfig } = useActions(stamphogSceneLogic)
    // Turning requests on asks teams on every pull request, and turning them off can leave pull requests
    // with no reviewer, so both directions take manager.
    const disabledReason = managerDisabledReason(toAccessControlLevel(repo.user_access_level)) ?? updatingReason
    const mode = repo.routing_mode ?? RoutingModeEnumApi.Off
    const on = mode !== RoutingModeEnumApi.Off

    return (
        <div className="flex flex-col gap-2">
            <OwnersFileState ownersFile={ownersFile} />
            <div className="flex flex-wrap items-center gap-2">
                <LemonSwitch
                    label="Request reviewers"
                    checked={on}
                    disabledReason={disabledReason}
                    // Waiting for the verdict is the default, because an approval then asks only the owners
                    // of sensitive and new paths.
                    onChange={(checked) =>
                        updateRepoConfig(repo.id, {
                            routing_mode: checked ? RoutingModeEnumApi.Fallback : RoutingModeEnumApi.Off,
                        })
                    }
                    data-attr="stamphog-repo-reviewer-requests-toggle"
                />
                {on && (
                    <LemonSelect
                        size="small"
                        value={mode}
                        disabledReason={disabledReason}
                        onChange={(routingMode) => updateRepoConfig(repo.id, { routing_mode: routingMode })}
                        options={[RoutingModeEnumApi.Fallback, RoutingModeEnumApi.Always].map((value) => ({
                            value,
                            label: ROUTING_MODE_LABELS[value],
                        }))}
                        data-attr="stamphog-repo-reviewer-requests-mode"
                    />
                )}
            </div>
        </div>
    )
}
