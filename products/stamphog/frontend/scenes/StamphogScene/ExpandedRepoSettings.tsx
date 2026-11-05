import { useActions, useValues } from 'kea'

import { LemonDivider, LemonSelect, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import {
    OwnersFileStatusEnumApi,
    ReviewModeEnumApi,
    RoutingModeEnumApi,
    type StamphogRepoConfigApi,
} from '../../generated/api.schemas'
import { REVIEW_MODE_LABELS } from '../../reviewModeLabels'
import { editorDisabledReason, managerDisabledReason } from './repoAccess'
import { ReviewerRequestSettings } from './ReviewerRequestSettings'
import { stamphogSceneLogic } from './stamphogSceneLogic'

const REVIEWER_REQUESTS_DESCRIPTION =
    'Asks the code owners in owners.yaml to review. Owners with a trivial part of the change are left out, and a comment on the pull request says why.'

const REVIEWER_REQUESTS_MODE_DESCRIPTION: Partial<Record<RoutingModeEnumApi, string>> = {
    [RoutingModeEnumApi.Fallback]: 'After a Stamphog approval, only the owners of sensitive and new paths are asked.',
    [RoutingModeEnumApi.Always]: 'Owners are asked as soon as a pull request is ready for review.',
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
        <section className="flex flex-col gap-2 min-w-0">
            <h5 className="text-muted mb-0">{title}</h5>
            {children}
            <p className="text-secondary text-xs m-0">{description}</p>
        </section>
    )
}

function TriggerSettings({
    repo,
    updatingReason,
}: {
    repo: StamphogRepoConfigApi
    updatingReason?: string
}): JSX.Element {
    const { triggerLabelFieldResets, savingTriggerLabelRepoIds } = useValues(stamphogSceneLogic)
    const { updateRepoConfig, triggerLabelEditStarted, resetTriggerLabelField } = useActions(stamphogSceneLogic)
    const accessReason = managerDisabledReason(toAccessControlLevel(repo.user_access_level))
    // Only the access level and the label's own save lock the label. An update elsewhere in the row
    // must not swap the editor out and drop its draft.
    const labelReadOnlyReason =
        accessReason ?? (savingTriggerLabelRepoIds.includes(repo.id) ? 'Saving the label' : null)
    const disabledReason = accessReason ?? updatingReason

    const saveTriggerLabel = (value: string): void => {
        const trimmed = value.trim()
        // Save only real changes. A save with no edit must not re-PATCH, and the API rejects a blank label.
        if (trimmed && trimmed !== repo.trigger_label) {
            updateRepoConfig(repo.id, { trigger_label: trimmed })
            return
        }
        resetTriggerLabelField(repo.id)
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                size="small"
                value={repo.review_mode ?? ReviewModeEnumApi.Label}
                disabledReason={disabledReason}
                onChange={(mode) => updateRepoConfig(repo.id, { review_mode: mode })}
                options={[
                    { value: ReviewModeEnumApi.All, label: REVIEW_MODE_LABELS[ReviewModeEnumApi.All] },
                    { value: ReviewModeEnumApi.Label, label: REVIEW_MODE_LABELS[ReviewModeEnumApi.Label] },
                ]}
                data-attr="stamphog-repo-review-mode"
            />
            {repo.review_mode === ReviewModeEnumApi.Label &&
                // EditableField has no disabled state, so a locked label reads as text.
                (labelReadOnlyReason ? (
                    <Tooltip title={labelReadOnlyReason}>
                        <span className="font-mono text-xs" data-attr="stamphog-repo-trigger-label">
                            {repo.trigger_label}
                        </span>
                    </Tooltip>
                ) : (
                    // A changed label silently stops reviews on pull requests that carry the old one, so a
                    // change takes the pencil and an explicit save, never a stray blur.
                    <EditableField
                        key={triggerLabelFieldResets[repo.id] ?? 0}
                        name="trigger_label"
                        value={repo.trigger_label ?? ''}
                        placeholder="Trigger label"
                        minLength={1}
                        compactButtons
                        onModeToggle={(mode) => {
                            if (mode === 'edit') {
                                triggerLabelEditStarted(repo.id)
                            }
                        }}
                        onSave={saveTriggerLabel}
                        className="font-mono text-xs"
                        data-attr="stamphog-repo-trigger-label"
                    />
                ))}
        </div>
    )
}

export function ExpandedRepoSettings({ repo }: { repo: StamphogRepoConfigApi }): JSX.Element {
    const { updatingRepoIds, ownersFileChecks } = useValues(stamphogSceneLogic)
    const { updateRepoConfig } = useActions(stamphogSceneLogic)
    const level = toAccessControlLevel(repo.user_access_level)
    const updatingReason = updatingRepoIds.includes(repo.id) ? 'Updating' : undefined
    const ownersFile = ownersFileChecks[repo.id]
    const routingMode = repo.routing_mode ?? RoutingModeEnumApi.Off
    // Requests read every owner from owners.yaml, so a repository without one is not offered them. A repository
    // that has them on keeps the setting in view, so it can be turned off.
    const showReviewerRequests = routingMode !== RoutingModeEnumApi.Off || ownersFile === OwnersFileStatusEnumApi.Found

    return (
        <div className="@container pl-2 pr-4 py-4">
            <div className="grid grid-cols-1 @2xl:grid-cols-3 gap-x-8 gap-y-6">
                <Section
                    title="Triggers"
                    description={
                        repo.review_mode === ReviewModeEnumApi.Label
                            ? 'Stamphog reviews a pull request once someone adds this label.'
                            : 'Stamphog reviews every pull request that is ready for review.'
                    }
                >
                    <TriggerSettings repo={repo} updatingReason={updatingReason} />
                </Section>
                <Section
                    title="Daily digest"
                    description="Posts the merged pull requests that Stamphog approved to Slack once a day."
                >
                    <LemonSwitch
                        label="Include in the digest"
                        checked={!!repo.digest_enabled}
                        // The API refuses a digest without reviews, because the digest lists only approved merges.
                        disabledReason={
                            editorDisabledReason(level) ??
                            (repo.enabled ? updatingReason : 'Turn reviews on to include this repository in the digest')
                        }
                        onChange={(checked) => updateRepoConfig(repo.id, { digest_enabled: checked })}
                        data-attr="stamphog-repo-digest-toggle"
                    />
                </Section>
                <Section
                    title="Reviews"
                    description="Pausing also takes the repository out of the digest. The trigger settings stay."
                >
                    <LemonSwitch
                        label="Review pull requests"
                        checked={repo.enabled}
                        // Pausing undoes a review decision, so it takes a higher level than turning reviews on.
                        disabledReason={
                            (repo.enabled ? managerDisabledReason(level) : editorDisabledReason(level)) ??
                            updatingReason
                        }
                        onChange={(checked) => updateRepoConfig(repo.id, { enabled: checked })}
                        data-attr="stamphog-repo-reviews-toggle"
                    />
                </Section>
            </div>
            {showReviewerRequests && (
                <>
                    <LemonDivider className="my-4" />
                    <div className="grid grid-cols-1 @2xl:grid-cols-3 gap-x-8">
                        <div className="@2xl:col-span-2">
                            <Section
                                title="Reviewer requests"
                                description={[
                                    REVIEWER_REQUESTS_DESCRIPTION,
                                    REVIEWER_REQUESTS_MODE_DESCRIPTION[routingMode],
                                ]
                                    .filter(Boolean)
                                    .join(' ')}
                            >
                                <ReviewerRequestSettings
                                    repo={repo}
                                    ownersFile={ownersFile}
                                    updatingReason={updatingReason}
                                />
                            </Section>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
