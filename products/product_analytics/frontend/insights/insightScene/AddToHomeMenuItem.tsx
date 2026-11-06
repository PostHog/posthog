import { useActions, useValues } from 'kea'

import { IconHome } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

import { HomePinInsight, homePinsLogic } from 'lib/components/AddToHome/homePinsLogic'

export function AddToHomeMenuItem({ insight }: { insight: HomePinInsight }): JSX.Element {
    const { homePinState } = useValues(homePinsLogic)
    const { toggleHomePin } = useActions(homePinsLogic)
    const { pinned, disabledReason } = homePinState(insight)

    return (
        <DropdownMenuItem
            data-attr="insight-more-menu-add-to-home"
            onClick={() => toggleHomePin(insight, 'insight_menu')}
            disabledReason={disabledReason}
        >
            <IconHome />
            {pinned ? 'Remove from home' : 'Add to home'}
        </DropdownMenuItem>
    )
}
