import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { reportAdventEntryClicked } from './adventEntryEvents'
import { AdventTreeIcon } from './AdventTreeIcon'
import { useAdventHoverSnow } from './useAdventHoverSnow'

const LABEL = 'Open the Workflows advent calendar'

export function AdventTodayNavTreeButton(): JSX.Element {
    const hoverSnow = useAdventHoverSnow()
    return (
        <span className="-my-1 inline-flex normal-case" {...hoverSnow}>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon-xs"
                            aria-label={LABEL}
                            data-attr="advent-entry-nav-tree"
                            onClick={() => reportAdventEntryClicked('nav-tree', 'today')}
                            render={<LinkPrimitive to={urls.workflowsAdventCalendar()} />}
                        />
                    }
                >
                    <AdventTreeIcon className="size-4 text-success" />
                </TooltipTrigger>
                <TooltipContent>{LABEL}</TooltipContent>
            </Tooltip>
        </span>
    )
}
