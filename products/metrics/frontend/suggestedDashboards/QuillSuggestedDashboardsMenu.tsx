import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconSparkles } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QuillSuggestionItem } from './QuillSuggestionItem'
import { suggestedDashboardsLogic } from './suggestedDashboardsLogic'

export function QuillSuggestedDashboardsMenu(): JSX.Element | null {
    const { suggestions, openingId, newSuggestionCount } = useValues(suggestedDashboardsLogic)
    const { openSuggestion, menuOpened } = useActions(suggestedDashboardsLogic)
    const { user } = useValues(userLogic)

    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Dashboard, AccessControlLevel.Editor) ??
        getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor)

    if (suggestions === null || (suggestions.length === 0 && !user?.is_staff)) {
        return null
    }

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open) {
                    menuOpened()
                }
            }}
        >
            <DropdownMenuTrigger render={<Button variant="outline" data-attr="metrics-suggested-dashboards-menu" />}>
                <IconSparkles className="text-ai" />
                <span
                    className={cn(
                        'rainbow-text font-semibold',
                        !(inStorybook() || inStorybookTestRunner()) && 'rainbow-text-animating'
                    )}
                >
                    Suggested
                </span>
                {newSuggestionCount > 0 && <Badge>{newSuggestionCount}</Badge>}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
                {suggestions.length > 0 && (
                    <DropdownMenuGroup>
                        {suggestions.map((suggestion) => (
                            <QuillSuggestionItem
                                key={suggestion.id}
                                suggestion={suggestion}
                                openingId={openingId}
                                openSuggestion={openSuggestion}
                                disabledReason={disabledReason}
                            />
                        ))}
                    </DropdownMenuGroup>
                )}
                {suggestions.length > 0 && user?.is_staff && <DropdownMenuSeparator />}
                {user?.is_staff && (
                    <DropdownMenuItem
                        onClick={() => router.actions.push(urls.metricsDashboardReview())}
                        data-attr="metrics-suggested-dashboards-review"
                    >
                        Review generated dashboards
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
