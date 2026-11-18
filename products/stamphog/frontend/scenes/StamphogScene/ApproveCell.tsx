import { useActions, useValues } from 'kea'

import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { StateDot } from 'lib/components/RepositoryList/StateDot'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import { type CodeReviewApprovalRepositoryApi } from '../../generated/api.schemas'
import {
    APPROVE_DOT_STATE,
    APPROVE_HINTS,
    APPROVE_OPTIONS,
    approveChoice,
    approveChoiceDisabledReason,
    approveChoicePatch,
} from './approveChoice'
import { managerDisabledReason } from './repoAccess'
import { stamphogSceneLogic } from './stamphogSceneLogic'

function TriggerLabelField({ repo }: { repo: CodeReviewApprovalRepositoryApi }): JSX.Element {
    const { triggerLabelFieldResets, savingTriggerLabelRepoIds } = useValues(stamphogSceneLogic)
    const { updateRepoConfig, triggerLabelEditStarted, resetTriggerLabelField } = useActions(stamphogSceneLogic)
    // Only the access level and the label's own save lock the label. An update elsewhere in the row
    // must not swap the editor out and drop its draft.
    const readOnlyReason =
        managerDisabledReason(toAccessControlLevel(repo.user_access_level)) ??
        (savingTriggerLabelRepoIds.includes(repo.id) ? 'Saving the label' : null)

    const saveTriggerLabel = (value: string): void => {
        const trimmed = value.trim()
        // Save only real changes. A save with no edit must not re-PATCH, and the API rejects a blank label.
        if (trimmed && trimmed !== repo.trigger_label) {
            updateRepoConfig(repo.id, { trigger_label: trimmed })
            return
        }
        resetTriggerLabelField(repo.id)
    }

    // EditableField has no disabled state, so a locked label reads as text.
    if (readOnlyReason) {
        return (
            <Tooltip title={readOnlyReason}>
                <span className="font-mono text-xs" data-attr="stamphog-repo-trigger-label">
                    {repo.trigger_label}
                </span>
            </Tooltip>
        )
    }
    // A changed label silently stops reviews on pull requests that carry the old one, so a change takes
    // the pencil and an explicit save, never a stray blur.
    return (
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
    )
}

export function ApproveCell({ repo }: { repo: CodeReviewApprovalRepositoryApi }): JSX.Element {
    const { updatingRepoIds } = useValues(stamphogSceneLogic)
    const { updateRepoConfig } = useActions(stamphogSceneLogic)
    const level = toAccessControlLevel(repo.user_access_level)
    const choice = approveChoice(repo)
    const options = APPROVE_OPTIONS.map((option) => ({
        ...option,
        icon: <StateDot state={APPROVE_DOT_STATE[option.value]} />,
        disabledReason: approveChoiceDisabledReason(repo, option.value, level) ?? undefined,
    }))
    // A viewer who can pick nothing but the current choice gets the reason on the select itself.
    const lockedReason = options.every((option) => option.value === choice || option.disabledReason)
        ? (managerDisabledReason(level) ?? undefined)
        : undefined
    const showsLabel = choice === 'label' || choice === 'label_or_clean_review'
    const hint = APPROVE_HINTS[choice]

    return (
        <div className="flex min-w-0 flex-col gap-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    aria-label={`Approve for ${repo.repository}`}
                    value={choice}
                    options={options}
                    onChange={(value) => {
                        const patch = approveChoicePatch(repo, value)
                        if (Object.keys(patch).length > 0) {
                            updateRepoConfig(repo.id, patch)
                        }
                    }}
                    disabledReason={lockedReason ?? (updatingRepoIds.includes(repo.id) ? 'Saving…' : undefined)}
                    data-attr="stamphog-repo-approve"
                />
                {showsLabel && (
                    <span className="flex min-w-0 items-center gap-1.5">
                        <span className="text-xs text-secondary">label</span>
                        <TriggerLabelField repo={repo} />
                    </span>
                )}
            </div>
            {hint && <span className="text-xs text-secondary">{hint}</span>}
        </div>
    )
}
