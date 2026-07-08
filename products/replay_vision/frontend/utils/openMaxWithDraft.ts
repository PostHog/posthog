import { SIDE_PANEL_PANEL_ID, maxLogic } from 'scenes/max/maxLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

/** Opens the PostHog AI side panel with a draft question seeded directly into its logic.
 * Never pass the draft through `openSidePanel` options: those mirror into the `#panel` URL hash,
 * which would leak session IDs and prompt text into history, copied links, and telemetry. */
export function openMaxWithDraft(message: string): void {
    let logic = maxLogic.findMounted({ panelId: SIDE_PANEL_PANEL_ID })
    if (!logic) {
        logic = maxLogic({ panelId: SIDE_PANEL_PANEL_ID })
        logic.mount() // the side panel's Max logic stays mounted for the app's lifetime
    }
    logic.actions.setQuestion(message)
    sidePanelStateLogic.findMounted()?.actions.openSidePanel(SidePanelTab.Max)
}
