import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { captureScratchpadLinkClicked, type ScratchpadEntryPoint } from '../../../inboxAnalytics'
import { inboxSceneLogic } from '../../../inboxSceneLogic'

/** Footer link from a scout's Told and Learned tabs to the scratchpad every scout writes to. */
export function OpenScratchpadButton({
    skillName,
    entryPoint,
}: {
    skillName: string
    entryPoint: ScratchpadEntryPoint
}): JSX.Element {
    const { setScratchpadOpen } = useActions(inboxSceneLogic)

    return (
        <LemonButton
            size="xsmall"
            type="tertiary"
            className="self-start"
            data-attr={`inbox-scout-open-scratchpad-${entryPoint}`}
            onClick={() => {
                captureScratchpadLinkClicked({ entryPoint, surface: 'scout_detail', skillName })
                setScratchpadOpen(true)
            }}
        >
            Open the scratchpad
        </LemonButton>
    )
}
