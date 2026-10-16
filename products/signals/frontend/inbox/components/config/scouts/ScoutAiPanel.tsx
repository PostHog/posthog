import { useActions, useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { useAttachedContext, useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'
import { SidePanelRunner } from 'products/posthog_ai/frontend/api/runner'

import { captureScoutAction } from '../../../inboxAnalytics'
import { SCOUT_NOTE_CREATE_TOOL, scoutAiContextItems, scoutAiLogic } from '../../../logics/scoutAiLogic'
import { scoutNotesLogic } from '../../../logics/scoutNotesLogic'

export function ScoutAiPanel({ panelId }: { panelId: string }): JSX.Element {
    const { scoutChatContext } = useValues(scoutAiLogic)
    useAttachedContext(scoutChatContext ? scoutAiContextItems(scoutChatContext) : null)

    return (
        <div className="flex flex-col flex-1 min-h-0 min-w-0">
            {scoutChatContext && <ScoutNoteSavedListener skillName={scoutChatContext.skillName} />}
            <SidePanelRunner
                panelId={panelId}
                attachApplyBackInstructions={false}
                composer={
                    scoutChatContext ? undefined : (
                        // `scoutChatContext` is in-memory, but the `inbox-scout` panel option round-trips
                        // through the URL hash. Filling the composer slot keeps the generic task composer
                        // out after a reload: a send from it would not be tied to any scout.
                        <EmptyMessage
                            title="No scout selected"
                            description="Reloading the page clears which scout this chat was about. Ask a question on the scout's page to start a new chat."
                        />
                    )
                }
            />
        </div>
    )
}

/** Shows a note the agent saved under Told, and counts it. */
function ScoutNoteSavedListener({ skillName }: { skillName: string }): null {
    const { loadNotes } = useActions(scoutNotesLogic({ skillName }))
    useToolStreamListener({
        tools: [SCOUT_NOTE_CREATE_TOOL],
        onEvent: (event) => {
            if (event.phase !== 'completed') {
                return
            }
            captureScoutAction({ actionType: 'save_note_from_ai', surface: 'scout_detail', skillName })
            loadNotes()
        },
    })
    return null
}
