import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { reportAdventEntryClicked, reportAdventEntryMiddleClicked } from './adventEntryEvents'
import { AdventTreeIcon } from './AdventTreeIcon'
import { useAdventHoverSnow } from './useAdventHoverSnow'

const LABEL = 'Open the Workflows advent calendar'

export function AdventTodayNavTreeButton(): JSX.Element {
    const hoverSnow = useAdventHoverSnow()
    return (
        <span className="-my-1 inline-flex normal-case">
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon-xs"
                            aria-label={LABEL}
                            data-attr="advent-entry-nav-tree"
                            onClickCapture={() => reportAdventEntryClicked('nav-tree', 'today')}
                            onAuxClick={(event) => reportAdventEntryMiddleClicked(event, 'nav-tree', 'today')}
                            {...hoverSnow}
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
