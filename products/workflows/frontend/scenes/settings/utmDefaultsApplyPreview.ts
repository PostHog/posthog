import { pluralize } from 'lib/utils/strings'

import type { ApplyUtmDefaultsResponseApi } from '../../generated/api.schemas'

export interface UtmDefaultsApplyState {
    preview: ApplyUtmDefaultsResponseApi | null
    previewLoading: boolean
    isPreviewCurrent: boolean
}

export function isNothingToUpdate(preview: ApplyUtmDefaultsResponseApi | null): boolean {
    return !!preview && preview.emails_updated === 0
}

export function applyUtmDefaultsDisabledReason({
    preview,
    previewLoading,
    isPreviewCurrent,
}: UtmDefaultsApplyState): string | undefined {
    return previewLoading || !preview || !isPreviewCurrent
        ? 'Counting the emails to update'
        : isNothingToUpdate(preview)
          ? 'No emails to update'
          : undefined
}

export function applyUtmDefaultsButtonLabel({ preview, isPreviewCurrent }: UtmDefaultsApplyState): string {
    return preview && isPreviewCurrent && !isNothingToUpdate(preview)
        ? `Update ${pluralize(preview.emails_updated, 'email')}`
        : 'Update emails'
}

export function utmDefaultsPreviewSummary(preview: ApplyUtmDefaultsResponseApi): string {
    const summary = isNothingToUpdate(preview)
        ? preview.emails_off > 0
            ? 'The emails left to update have UTM tags off.'
            : 'Every email already uses these values.'
        : `${pluralize(preview.emails_updated, 'email')} in ${pluralize(preview.workflows_updated, 'broadcast or workflow', 'broadcasts and workflows')} will use the new values.`
    const liveSuffix =
        preview.active_workflows_updated > 0
            ? ` ${preview.active_workflows_updated} of them ${preview.active_workflows_updated === 1 ? 'is' : 'are'} live, so the next send uses the new values.`
            : ''

    return `${summary}${liveSuffix}`
}
