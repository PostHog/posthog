import type { ValueSuggestionsStatus } from './filtersEditorLogic'

export function suggestionsEmptyText(status: ValueSuggestionsStatus): string {
    switch (status) {
        case 'loading':
            return 'Loading suggestions…'
        case 'error':
            return "Couldn't load suggestions"
        case 'loaded':
            return 'No matching suggestions'
        default:
            return 'Type a value to add it'
    }
}
