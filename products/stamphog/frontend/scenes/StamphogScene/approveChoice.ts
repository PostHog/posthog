import type { DotState } from 'lib/components/RepositoryList/StateDot'

import { AccessControlLevel } from '~/types'

import {
    ReviewModeEnumApi,
    type CodeReviewApprovalRepositoryApi,
    type PatchedCodeReviewApprovalRepositoryWriteApi,
} from '../../generated/api.schemas'
import { editorDisabledReason, managerDisabledReason } from './repoAccess'

/**
 * The one Approve choice of a repository. The backend keeps three fields: `enabled`,
 * `review_mode` and `review_on_clean_external_review`. Each choice is one combination of them.
 */
export type ApproveChoice = 'label' | 'label_or_clean_review' | 'all' | 'paused'

export const APPROVE_OPTIONS: { value: ApproveChoice; label: string; tooltip: string }[] = [
    {
        value: 'label',
        label: 'On label',
        tooltip: 'Reviews a pull request once someone adds the trigger label.',
    },
    {
        value: 'label_or_clean_review',
        label: 'On label, or after a clean review',
        tooltip:
            'Also reviews a pull request after a Standard review finds no issues. It posts only an approval. This needs Standard reviews on for the repository.',
    },
    {
        value: 'all',
        label: 'Every pull request',
        tooltip: 'Reviews every pull request that is ready for review.',
    },
    {
        value: 'paused',
        label: 'Paused',
        tooltip: 'Reviews nothing and leaves the repository out of the daily digest. The other settings stay.',
    },
]

/** The line under the select, for the choices whose effect the label alone does not say. */
export const APPROVE_HINTS: Partial<Record<ApproveChoice, string>> = {
    label_or_clean_review: 'Tries once, silently, after PostHog Review finds nothing. Posts only an approval.',
    paused: 'Settings stay. Resume to approve again.',
}

// A label covers only the pull requests someone marks, so it gets the open dot.
export const APPROVE_DOT_STATE: Record<ApproveChoice, DotState> = {
    label: 'partial',
    label_or_clean_review: 'on',
    all: 'on',
    paused: 'off',
}

export function approveChoice(repo: CodeReviewApprovalRepositoryApi): ApproveChoice {
    if (!repo.enabled) {
        return 'paused'
    }
    if (repo.review_mode === ReviewModeEnumApi.All) {
        return 'all'
    }
    return repo.review_on_clean_external_review ? 'label_or_clean_review' : 'label'
}

/**
 * The fields to send for a choice. Only changed fields go in the patch, because the backend asks
 * for manager access for every review policy field that a write names, even an unchanged one.
 * Paused keeps the review mode, so resuming a paused repository sends `enabled` alone.
 */
export function approveChoicePatch(
    repo: CodeReviewApprovalRepositoryApi,
    choice: ApproveChoice
): PatchedCodeReviewApprovalRepositoryWriteApi {
    if (choice === 'paused') {
        return repo.enabled ? { enabled: false } : {}
    }
    const patch: PatchedCodeReviewApprovalRepositoryWriteApi = {}
    if (!repo.enabled) {
        patch.enabled = true
    }
    const reviewMode = choice === 'all' ? ReviewModeEnumApi.All : ReviewModeEnumApi.Label
    if (reviewMode !== repo.review_mode) {
        patch.review_mode = reviewMode
    }
    // Every pull request turns the clean review trigger off on the backend, so the patch leaves it out.
    const cleanReview = choice === 'label_or_clean_review'
    if (choice !== 'all' && cleanReview !== repo.review_on_clean_external_review) {
        patch.review_on_clean_external_review = cleanReview
    }
    return patch
}

/** Why the viewer cannot pick a choice, or null. Turning reviews on needs editor, every other change needs manager. */
export function approveChoiceDisabledReason(
    repo: CodeReviewApprovalRepositoryApi,
    choice: ApproveChoice,
    level: AccessControlLevel | undefined
): string | null {
    const patch = approveChoicePatch(repo, choice)
    const fields = Object.keys(patch)
    if (fields.length === 0) {
        return null
    }
    if (fields.length === 1 && patch.enabled === true) {
        return editorDisabledReason(level)
    }
    return managerDisabledReason(level)
}
