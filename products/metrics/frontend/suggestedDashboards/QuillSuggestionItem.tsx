import { IconCheckCircle, IconX } from '@posthog/icons'
import { Button, DropdownMenuItem, Spinner } from '@posthog/quill'

import type { MetricsSuggestedDashboardApi } from 'products/metrics/frontend/generated/api.schemas'

import { DISMISS_SUGGESTION_LABEL } from './dismissSuggestionLabel'

export function QuillSuggestionItem({
    suggestion,
    openingId,
    openSuggestion,
    dismissSuggestion,
    disabledReason,
}: {
    suggestion: MetricsSuggestedDashboardApi
    openingId: string | null
    openSuggestion: (suggestion: MetricsSuggestedDashboardApi) => void
    dismissSuggestion: (suggestion: MetricsSuggestedDashboardApi) => void
    disabledReason: string | null
}): JSX.Element {
    const created = suggestion.dashboard_id !== null
    return (
        // The dismiss button is a second menu item beside the row, because a button cannot hold a button.
        <div className="flex items-center gap-0.5">
            <div className="min-w-0 flex-1">
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
            </div>
            <DropdownMenuItem
                // The menu stays open, so that a user can dismiss several suggestions.
                closeOnClick={false}
                nativeButton
                render={<Button size="icon" className="text-muted-foreground" />}
                onClick={() => dismissSuggestion(suggestion)}
                aria-label={DISMISS_SUGGESTION_LABEL}
                tooltip={DISMISS_SUGGESTION_LABEL}
                disabledReason={disabledReason}
                data-attr="metrics-suggested-dashboard-dismiss"
            >
                <IconX />
            </DropdownMenuItem>
        </div>
    )
}
