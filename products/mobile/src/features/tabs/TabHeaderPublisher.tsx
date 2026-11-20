import { type TabKey, useTabHeader } from './tabHeaderStore'

interface TabHeaderPublisherProps {
    scrollToTop?: () => void
    liveAudience?: boolean
    tab: TabKey
    status: string | null
    hint?: string | null
    refreshing?: boolean
}

/**
 * A pinned screen's status line in the shared tabs header. Its own component, so the same screen pushed above the tabs
 * never writes the tab's header slot, and never clears it when it closes.
 */
export function TabHeaderPublisher({
    tab,
    scrollToTop,
    status,
    hint = null,
    refreshing = false,
    liveAudience = false,
}: TabHeaderPublisherProps): null {
    useTabHeader(tab, {
        scrollToTop,
        refreshing,
        hint,
        status,
        editing: null,
        editPins: null,
        filter: null,
        liveAudience,
    })
    return null
}
