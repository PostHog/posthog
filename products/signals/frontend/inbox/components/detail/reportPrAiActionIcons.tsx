import { IconCheckCircle, IconGitBranch, IconPullRequest } from '@posthog/icons'

import { ReportPrAiActionKey } from '../../logics/reportQuickAskLogic'

export const REPORT_PR_AI_ACTION_ICONS: Record<ReportPrAiActionKey, JSX.Element> = {
    merge_pr: <IconGitBranch />,
    fix_ci: <IconCheckCircle />,
    resolve_conflicts: <IconPullRequest />,
}
