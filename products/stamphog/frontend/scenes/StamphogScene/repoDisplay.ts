import { LemonTagType } from 'lib/lemon-ui/LemonTag'

import { ReviewModeEnumApi, type StamphogRepoConfigApi } from '../../generated/api.schemas'
import { REVIEW_MODE_LABELS } from '../../reviewModeLabels'

export function repoStatusDisplay(repo: StamphogRepoConfigApi): { type: LemonTagType; label: string } {
    if (repo.enabled) {
        return { type: 'success', label: 'Reviewing' }
    }
    return { type: 'muted', label: 'Paused' }
}

export function triggerSummary(repo: StamphogRepoConfigApi): string {
    if (repo.review_mode === ReviewModeEnumApi.Label) {
        return `Label: ${repo.trigger_label ?? ''}`
    }
    return REVIEW_MODE_LABELS[ReviewModeEnumApi.All]
}
