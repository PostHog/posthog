import { AccessControlLevel } from '~/types'

import type {
    CodeReviewApprovalRepositoryApi,
    PatchedCodeReviewApprovalRepositoryWriteApi,
} from '../../generated/api.schemas'
import { ApproveChoice, approveChoice, approveChoiceDisabledReason, approveChoicePatch } from './approveChoice'

const repo = (overrides: Partial<CodeReviewApprovalRepositoryApi>): CodeReviewApprovalRepositoryApi =>
    ({
        id: 'repo',
        repository: 'example-org/web',
        enabled: true,
        review_mode: 'label',
        review_on_clean_external_review: false,
        ...overrides,
    }) as CodeReviewApprovalRepositoryApi

describe('approveChoice', () => {
    test.each<[string, CodeReviewApprovalRepositoryApi, ApproveChoice]>([
        ['label', repo({}), 'label'],
        [
            'label with the clean review trigger',
            repo({ review_on_clean_external_review: true }),
            'label_or_clean_review',
        ],
        ['every pull request', repo({ review_mode: 'all' }), 'all'],
        ['a paused repository whatever its mode', repo({ enabled: false, review_mode: 'all' }), 'paused'],
    ])('reads %s', (_name, current, expected) => {
        expect(approveChoice(current)).toEqual(expected)
    })

    // The backend asks for manager access for every policy field a write names, so a patch must
    // carry only the fields that change, or an editor could never resume a paused repository.
    test.each<[string, CodeReviewApprovalRepositoryApi, ApproveChoice, PatchedCodeReviewApprovalRepositoryWriteApi]>([
        ['resumes a paused label repository with enabled alone', repo({ enabled: false }), 'label', { enabled: true }],
        ['resumes into another mode', repo({ enabled: false }), 'all', { enabled: true, review_mode: 'all' }],
        ['pauses without touching the mode', repo({ review_mode: 'all' }), 'paused', { enabled: false }],
        ['adds the clean review trigger', repo({}), 'label_or_clean_review', { review_on_clean_external_review: true }],
        [
            'moves from every pull request to the clean review trigger',
            repo({ review_mode: 'all' }),
            'label_or_clean_review',
            { review_mode: 'label', review_on_clean_external_review: true },
        ],
        [
            'leaves the clean review trigger to the backend for every pull request',
            repo({ review_on_clean_external_review: true }),
            'all',
            { review_mode: 'all' },
        ],
        ['sends nothing for the current choice', repo({}), 'label', {}],
    ])('%s', (_name, current, choice, expected) => {
        expect(approveChoicePatch(current, choice)).toEqual(expected)
    })

    test.each<[string, CodeReviewApprovalRepositoryApi, ApproveChoice, boolean]>([
        ['an editor may resume a paused repository', repo({ enabled: false }), 'label', false],
        ['an editor may not pause', repo({}), 'paused', true],
        ['an editor may not change the mode', repo({}), 'all', true],
    ])('%s', (_name, current, choice, disabled) => {
        expect(approveChoiceDisabledReason(current, choice, AccessControlLevel.Editor) !== null).toBe(disabled)
    })
})
