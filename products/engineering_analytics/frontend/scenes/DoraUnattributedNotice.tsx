import { useValues } from 'kea'

import { doraLogic } from './doraLogic'

export function DoraUnattributedNotice(): JSX.Element | null {
    const { dora } = useValues(doraLogic)

    if (dora?.unattributed_merged_pr_share == null || dora.unattributed_merged_pr_share <= 0) {
        return null
    }

    return (
        <div className="mt-2 text-xs text-tertiary" data-attr="engineering-analytics-dora-unattributed">
            {(dora.unattributed_merged_pr_share * 100).toFixed(1)}% of the {dora.merged_pr_count} PRs merged in this
            window have no deploy attributed yet, usually because their deploy hasn't happened or synced.
        </div>
    )
}
