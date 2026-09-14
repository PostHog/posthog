import { useActions, useValues } from 'kea'

import type { ScoutSuggestionSurface } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { suggestionToCreateValues } from '../../../utils/scoutSuggestions'
import { ScoutCreateModalHost } from './ScoutCreateModalHost'

/**
 * The create form opened from a suggestion. A custom draft pre-fills it; a canonical pick fills it
 * from the scout that already exists, and submitting turns that scout on. Either way the form is
 * the "read the whole thing" surface, so the name, cadence and body are all visible before the
 * scout starts running.
 */
export function ScoutSuggestionCreateHost({ surface }: { surface: ScoutSuggestionSurface }): JSX.Element | null {
    const { createFromSuggestion } = useValues(scoutSuggestionsLogic)
    const { closeCreateFromSuggestion, suggestionCreated } = useActions(scoutSuggestionsLogic)
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    const handleDone = (): void => {
        if (createFromSuggestion) {
            suggestionCreated(createFromSuggestion.item, surface)
        }
        loadScoutConfigs()
    }

    return (
        <ScoutCreateModalHost
            initialValues={
                createFromSuggestion
                    ? suggestionToCreateValues(createFromSuggestion.item, createFromSuggestion.existing)
                    : null
            }
            onClose={closeCreateFromSuggestion}
            onCreated={handleDone}
            onEnabled={handleDone}
        />
    )
}
