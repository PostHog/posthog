import { useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { organizationLogic } from 'scenes/organizationLogic'

export function ComposerDataAccessIndicator(): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)

    if (currentOrganization?.ai_data_access !== 'metadata_only') {
        return null
    }

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        tabIndex={0}
                        className="flex items-center gap-1 rounded px-1 text-xs text-muted-foreground"
                        data-attr="composer-data-access-indicator"
                    >
                        <IconLock className="shrink-0" />
                        <span className="@max-[480px]/composer:hidden">No data access</span>
                    </span>
                }
            />
            <TooltipContent>
                PostHog AI can't see this project's data. It can still make changes, and charts load only in your
                browser. An admin sets this in organization AI settings.
            </TooltipContent>
        </Tooltip>
    )
}
