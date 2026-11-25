import { CodeReviewTab, codeReviewTabFromSearchParams, visibleCodeReviewTabs } from './codeReviewTabs'

describe('codeReviewTabFromSearchParams', () => {
    test.each<[string, Record<string, any>, boolean, CodeReviewTab]>([
        ['no tab param', {}, true, 'activity'],
        ['a current key', { tab: 'code_you_own' }, true, 'code_you_own'],
        ['an unknown key', { tab: 'nonsense' }, true, 'activity'],
        ['the old team view key', { tab: 'team_changes' }, true, 'code_you_own'],
        ['the old auto-approvals view', { activity: 'auto_approvals' }, true, 'approval_history'],
        ['no tab param without the flag', {}, false, 'approval_settings'],
        ['a review tab without the flag', { tab: 'settings' }, false, 'approval_settings'],
        ['an approval tab without the flag', { tab: 'approval_history' }, false, 'approval_history'],
    ])('opens the right tab for %s', (_name, searchParams, reviewsEnabled, expected) => {
        expect(codeReviewTabFromSearchParams(searchParams, reviewsEnabled)).toEqual(expected)
    })

    test.each<[boolean, CodeReviewTab[]]>([
        [true, ['activity', 'code_you_own', 'settings', 'approval_settings', 'approval_history']],
        [false, ['code_you_own', 'approval_settings', 'approval_history']],
    ])('shows the tabs in order with the review-hog flag %s', (reviewsEnabled, expected) => {
        expect(visibleCodeReviewTabs(reviewsEnabled).map((tab) => tab.key)).toEqual(expected)
    })
})
