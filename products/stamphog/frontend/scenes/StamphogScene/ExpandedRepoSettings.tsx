import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import {
    OwnersFileStatusEnumApi,
    RoutingModeEnumApi,
    type CodeReviewApprovalRepositoryApi,
} from '../../generated/api.schemas'
import { editorDisabledReason } from './repoAccess'
import { type OwnersFileCheck, stamphogSceneLogic } from './stamphogSceneLogic'

const REVIEWER_REQUESTS_DESCRIPTION: Record<RoutingModeEnumApi, string> = {
    [RoutingModeEnumApi.Off]:
        'Reviewer requests ask the code owners in owners.yaml to review. Owners with a trivial part of the change are left out, and a comment on the pull request says why.',
    [RoutingModeEnumApi.Fallback]:
        'Code owners are asked when auto-approval does not approve. After an approval, only the owners of sensitive and new paths are asked.',
    [RoutingModeEnumApi.Always]: 'Code owners are asked as soon as a pull request is ready for review.',
}

function Section({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex min-w-0 flex-col gap-2">
            <h5 className="mb-0 text-muted">{title}</h5>
            {children}
            <p className="m-0 text-xs text-secondary">{description}</p>
        </section>
    )
}

function OwnersFileState({ ownersFile }: { ownersFile: OwnersFileCheck | undefined }): JSX.Element {
    switch (ownersFile) {
        case OwnersFileStatusEnumApi.Found:
            return (
                <span className="flex items-center gap-1 text-sm text-success" data-attr="stamphog-owners-file-found">
                    <IconCheckCircle />
                    owners.yaml found
                </span>
            )
        case OwnersFileStatusEnumApi.Missing:
            return (
                <span className="flex items-center gap-1 text-sm text-warning">
                    <IconWarning />
                    No owners.yaml on the default branch, so nobody gets a review request.
                </span>
            )
        case OwnersFileStatusEnumApi.Unavailable:
            return (
                <span className="text-sm text-secondary">Couldn't check for owners.yaml. Reopen the row to retry.</span>
            )
        default:
            return (
                <span className="flex items-center gap-1 text-sm text-secondary">
                    <Spinner />
                    Checking for owners.yaml
                </span>
            )
    }
}

export function ExpandedRepoSettings({ repo }: { repo: CodeReviewApprovalRepositoryApi }): JSX.Element {
    const { updatingRepoIds, ownersFileChecks } = useValues(stamphogSceneLogic)
    const { updateRepoConfig } = useActions(stamphogSceneLogic)
    const level = toAccessControlLevel(repo.user_access_level)
    const updatingReason = updatingRepoIds.includes(repo.id) ? 'Saving…' : undefined
    const routingMode = repo.routing_mode ?? RoutingModeEnumApi.Off

    return (
        <div className="@container py-4 pr-4 pl-2">
            <div className="grid grid-cols-1 gap-x-8 gap-y-6 @2xl:grid-cols-3">
                <Section
                    title="Daily digest"
                    description="Posts the merged pull requests that auto-approval approved to Slack once a day."
                >
                    <LemonSwitch
                        label="Include in the digest"
                        checked={!!repo.digest_enabled}
                        // The API refuses a digest without reviews, because the digest lists only approved merges.
                        disabledReason={
                            editorDisabledReason(level) ??
                            (repo.enabled ? updatingReason : 'Pick an Approve option other than Paused first')
                        }
                        onChange={(checked) => updateRepoConfig(repo.id, { digest_enabled: checked })}
                        data-attr="stamphog-repo-digest-toggle"
                    />
                </Section>
                <Section title="Reviewer requests" description={REVIEWER_REQUESTS_DESCRIPTION[routingMode]}>
                    <OwnersFileState ownersFile={ownersFileChecks[repo.id]} />
                </Section>
                <Section title="Added" description="When this repository was added to auto-approval.">
                    <span className="text-sm">
                        <TZLabel time={repo.created_at} />
                    </span>
                </Section>
            </div>
        </div>
    )
}
