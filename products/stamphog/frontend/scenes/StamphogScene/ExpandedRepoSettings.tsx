import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import { ReviewModeEnumApi, type StamphogRepoConfigApi } from '../../generated/api.schemas'
import { REVIEW_MODE_LABELS } from '../../reviewModeLabels'
import { editorDisabledReason, managerDisabledReason } from './repoAccess'
import { stamphogSceneLogic } from './stamphogSceneLogic'

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
    const { updateRepoConfig } = useActions(stamphogSceneLogic)
    const disabledReason = managerDisabledReason(toAccessControlLevel(repo.user_access_level)) ?? updatingReason

    const saveTriggerLabel = (value: string): void => {
        const trimmed = value.trim()
        // Save only real changes — blur after no edit (or after enter already saved) must not re-PATCH,
        // and a blank label is rejected by the API anyway.
        if (trimmed && trimmed !== repo.trigger_label) {
            updateRepoConfig(repo.id, { trigger_label: trimmed })
        }
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                size="small"
                value={repo.review_mode ?? ReviewModeEnumApi.All}
                disabledReason={disabledReason}
                onChange={(mode) => updateRepoConfig(repo.id, { review_mode: mode })}
                options={[
                    { value: ReviewModeEnumApi.All, label: REVIEW_MODE_LABELS[ReviewModeEnumApi.All] },
                    { value: ReviewModeEnumApi.Label, label: REVIEW_MODE_LABELS[ReviewModeEnumApi.Label] },
                ]}
                data-attr="stamphog-repo-review-mode"
            />
            {repo.review_mode === ReviewModeEnumApi.Label && (
                <LemonInput
                    // Uncontrolled on purpose: the label saves on blur/enter, not per keystroke.
                    // Keying by the saved value resets the draft after a reload.
                    key={`${repo.id}-${repo.trigger_label}`}
                    size="small"
                    className="w-40"
                    defaultValue={repo.trigger_label}
                    placeholder="Trigger label"
                    disabledReason={disabledReason}
                    onBlur={(e) => saveTriggerLabel(e.currentTarget.value)}
                    onPressEnter={(e) => saveTriggerLabel(e.currentTarget.value)}
                    data-attr="stamphog-repo-trigger-label"
                />
            )}
        </div>
    )
}

export function ExpandedRepoSettings({ repo }: { repo: StamphogRepoConfigApi }): JSX.Element {
    const { updatingRepoIds } = useValues(stamphogSceneLogic)
    const { updateRepoConfig } = useActions(stamphogSceneLogic)
    const level = toAccessControlLevel(repo.user_access_level)
    const updatingReason = updatingRepoIds.includes(repo.id) ? 'Updating' : undefined

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
        </div>
    )
}
