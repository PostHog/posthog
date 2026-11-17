import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import { type CodeReviewApprovalRepositoryApi } from '../../generated/api.schemas'
import { editorDisabledReason } from './repoAccess'
import { stamphogSceneLogic } from './stamphogSceneLogic'

export function DigestCell({ repo }: { repo: CodeReviewApprovalRepositoryApi }): JSX.Element {
    const { updatingRepoIds } = useValues(stamphogSceneLogic)
    const { updateRepoConfig } = useActions(stamphogSceneLogic)

    return (
        <LemonSwitch
            aria-label={`Include ${repo.repository} in the digest`}
            checked={!!repo.digest_enabled}
            // The API refuses a digest without reviews, because the digest lists only approved merges.
            disabledReason={
                editorDisabledReason(toAccessControlLevel(repo.user_access_level)) ??
                (!repo.enabled
                    ? 'Pick an Approve option other than Paused first'
                    : updatingRepoIds.includes(repo.id)
                      ? 'Saving…'
                      : undefined)
            }
            onChange={(checked) => updateRepoConfig(repo.id, { digest_enabled: checked })}
            data-attr="stamphog-repo-digest-toggle"
        />
    )
}
