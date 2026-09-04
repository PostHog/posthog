import { useActions, useValues } from 'kea'

import type { ScoutSuggestionSurface } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { suggestionToCreateValues } from '../../../utils/scoutSuggestions'
import { ScoutCreateModalHost } from './ScoutCreateModalHost'

/**
 * The create form opened from a custom suggestion, pre-filled with its draft. The form is the
 * "read the whole draft" surface too, so the name, cadence and body are all visible before the
 * scout starts running.
 */
export function ScoutSuggestionCreateHost({ surface }: { surface: ScoutSuggestionSurface }): JSX.Element | null {
    const { createFromSuggestion } = useValues(scoutSuggestionsLogic)
    const { closeCreateFromSuggestion, suggestionCreated } = useActions(scoutSuggestionsLogic)
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    return (
        <ScoutCreateModalHost
            initialValues={createFromSuggestion ? suggestionToCreateValues(createFromSuggestion) : null}
            onClose={closeCreateFromSuggestion}
            onCreated={() => {
                if (createFromSuggestion) {
                    suggestionCreated(createFromSuggestion, surface)
                }
                loadScoutConfigs()
            }}
        />
    )
}
