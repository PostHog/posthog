import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconChevronDown, IconSparkles } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonMenu, LemonMenuItem, LemonMenuSection, Spinner } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { MetricsSuggestedDashboardApi } from 'products/metrics/frontend/generated/api.schemas'

import { suggestedDashboardsLogic } from './suggestedDashboardsLogic'

function suggestionItem(
    suggestion: MetricsSuggestedDashboardApi,
    openingId: string | null,
    openSuggestion: (suggestion: MetricsSuggestedDashboardApi) => void,
    disabledReason: string | null
): LemonMenuItem {
    const created = suggestion.dashboard_id !== null
    return {
        label: (
            <div className="flex flex-col min-w-0 max-w-80">
                <span className="truncate">{suggestion.name}</span>
                <span className="truncate text-xs text-secondary">
                    {suggestion.reason || `${suggestion.panel_count} charts`}
                </span>
            </div>
        ),
        sideIcon:
            openingId === suggestion.id ? (
                <Spinner />
            ) : created ? (
                <IconCheckCircle className="text-success" />
            ) : undefined,
        tooltip: created ? 'Created. Open the dashboard.' : undefined,
        disabledReason: created ? undefined : (disabledReason ?? undefined),
        onClick: () => openSuggestion(suggestion),
        'data-attr': 'metrics-suggested-dashboard',
    }
}

export function SuggestedDashboardsMenu(): JSX.Element | null {
    const { suggestions, openingId, newSuggestionCount } = useValues(suggestedDashboardsLogic)
    const { openSuggestion, menuOpened } = useActions(suggestedDashboardsLogic)
    const { user } = useValues(userLogic)

    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Dashboard, AccessControlLevel.Editor) ??
        getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor)

    if (suggestions === null || (suggestions.length === 0 && !user?.is_staff)) {
        return null
    }

    const sections: LemonMenuSection[] = []
    if (suggestions.length) {
        sections.push({
            items: suggestions.map((suggestion) =>
                suggestionItem(suggestion, openingId, openSuggestion, disabledReason)
            ),
        })
    }
    if (user?.is_staff) {
        sections.push({
            items: [
                {
                    label: 'Review generated dashboards',
                    to: urls.metricsDashboardReview(),
                    'data-attr': 'metrics-suggested-dashboards-review',
                },
            ],
        })
    }

    return (
        <LemonMenu
            items={sections}
            onVisibilityChange={(visible) => {
                if (visible) {
                    menuOpened()
                }
            }}
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconSparkles className="text-ai" />}
                sideIcon={<IconChevronDown />}
                data-attr="metrics-suggested-dashboards-menu"
            >
                <span className="flex items-center gap-1">
                    <span
                        className={cn(
                            'rainbow-text font-semibold',
                            !(inStorybook() || inStorybookTestRunner()) && 'rainbow-text-animating'
                        )}
                    >
                        Suggested
                    </span>
                    {newSuggestionCount > 0 && (
                        <LemonBadge.Number count={newSuggestionCount} size="small" status="muted" />
                    )}
                </span>
            </LemonButton>
        </LemonMenu>
    )
}
