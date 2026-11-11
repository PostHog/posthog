import { IconCheckCircle } from '@posthog/icons'
import { DropdownMenuItem, Spinner } from '@posthog/quill'

import type { MetricsSuggestedDashboardApi } from 'products/metrics/frontend/generated/api.schemas'

export function QuillSuggestionItem({
    suggestion,
    openingId,
    openSuggestion,
    disabledReason,
}: {
    suggestion: MetricsSuggestedDashboardApi
    openingId: string | null
    openSuggestion: (suggestion: MetricsSuggestedDashboardApi) => void
    disabledReason: string | null
}): JSX.Element {
    const created = suggestion.dashboard_id !== null
    return (
        <DropdownMenuItem
            onClick={() => openSuggestion(suggestion)}
            tooltip={created ? 'Created. Open the dashboard.' : undefined}
            disabledReason={created ? null : disabledReason}
            data-attr="metrics-suggested-dashboard"
            description={suggestion.reason || `${suggestion.panel_count} charts`}
        >
            <span className="truncate max-w-80">{suggestion.name}</span>
            {openingId === suggestion.id ? (
                <Spinner className="ml-auto" />
            ) : created ? (
                <IconCheckCircle className="ml-auto text-success" />
            ) : null}
        </DropdownMenuItem>
    )
}
