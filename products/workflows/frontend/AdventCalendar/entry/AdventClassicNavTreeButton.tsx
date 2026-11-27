import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { reportAdventEntryClicked, reportAdventEntryMiddleClicked } from './adventEntryEvents'
import { AdventTreeIcon } from './AdventTreeIcon'
import { useAdventHoverSnow } from './useAdventHoverSnow'

const LABEL = 'Open the Workflows advent calendar'

export function AdventClassicNavTreeButton(): JSX.Element {
    const hoverSnow = useAdventHoverSnow()
    return (
        <span className="-my-1.5 inline-flex">
            <LemonButton
                size="xsmall"
                icon={<AdventTreeIcon className="size-4 text-success" />}
                tooltip={LABEL}
                tooltipPlacement="right"
                aria-label={LABEL}
                to={urls.workflowsAdventCalendar()}
                onClickCapture={() => reportAdventEntryClicked('nav-tree', 'classic')}
                onAuxClick={(event) => reportAdventEntryMiddleClicked(event, 'nav-tree', 'classic')}
                {...hoverSnow}
                data-attr="advent-entry-nav-tree"
            />
        </span>
    )
}
