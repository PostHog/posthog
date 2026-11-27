import { useValues } from 'kea'
import { useState } from 'react'

import { IconShare } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventShareModal } from './AdventShareModal'

export function AdventShareButton(): JSX.Element | null {
    const { openCount, revealingDoor } = useValues(adventCalendarLogic)
    const [isSharing, setSharing] = useState(false)

    if (openCount === 0) {
        return null
    }

    return (
        <>
            <LemonButton
                type="primary"
                icon={<IconShare />}
                data-attr="advent-share"
                disabledReason={revealingDoor ? 'Share after the door opens' : null}
                onClick={() => setSharing(true)}
            >
                Share
            </LemonButton>
            <AdventShareModal isOpen={isSharing} onClose={() => setSharing(false)} />
        </>
    )
}
