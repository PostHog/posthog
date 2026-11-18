import type { LemonTab } from '@posthog/lemon-ui'

export type CodeReviewTab = 'activity' | 'code_you_own' | 'settings' | 'approval_settings' | 'approval_history'

const TABS: CodeReviewTab[] = ['activity', 'code_you_own', 'settings', 'approval_settings', 'approval_history']

/** The tabs of PostHog Review itself. They need the review-hog flag, the auto-approval tabs do not. */
export function isReviewTab(tab: CodeReviewTab): boolean {
    return tab === 'activity' || tab === 'settings'
}

export function defaultCodeReviewTab(reviewsEnabled: boolean): CodeReviewTab {
    return reviewsEnabled ? 'activity' : 'approval_settings'
}

/**
 * The tab a Code review URL opens. Links from before the auto-approval tabs existed still work:
 * `?tab=team_changes` opens Code you own and `?activity=auto_approvals` opens Approval history.
 * Without the review-hog flag a review tab is not shown, so its link opens the default tab instead.
 */
export function codeReviewTabFromSearchParams(
    searchParams: Record<string, any>,
    reviewsEnabled: boolean
): CodeReviewTab {
    let tab: CodeReviewTab | undefined = TABS.find((candidate) => candidate === searchParams.tab)
    if (searchParams.tab === 'team_changes') {
        tab = 'code_you_own'
    } else if (!tab && searchParams.activity === 'auto_approvals') {
        tab = 'approval_history'
    }
    if (!tab || (isReviewTab(tab) && !reviewsEnabled)) {
        return defaultCodeReviewTab(reviewsEnabled)
    }
    return tab
}

export function visibleCodeReviewTabs(reviewsEnabled: boolean): LemonTab<CodeReviewTab>[] {
    const tabs: LemonTab<CodeReviewTab>[] = [
        { key: 'activity', label: 'Review activity', 'data-attr': 'code-review-tab-activity' },
        { key: 'code_you_own', label: 'Code you own', 'data-attr': 'code-review-tab-code-you-own' },
        { key: 'settings', label: 'Review settings', 'data-attr': 'code-review-tab-settings' },
        { key: 'approval_settings', label: 'Approval settings', 'data-attr': 'code-review-tab-approval-settings' },
        { key: 'approval_history', label: 'Approval history', 'data-attr': 'code-review-tab-approval-history' },
    ]
    return reviewsEnabled ? tabs : tabs.filter((tab) => !isReviewTab(tab.key))
}
