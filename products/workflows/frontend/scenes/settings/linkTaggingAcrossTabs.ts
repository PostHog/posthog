// pinned: localStorage key - an Impact tab in another window listens for it, so renaming it breaks that refresh
export const LINK_TAGGING_SAVED_KEY = 'posthog-workflows-link-tagging-saved'

export function announceLinkTaggingSaved(): void {
    localStorage.setItem(LINK_TAGGING_SAVED_KEY, String(Date.now()))
}

// The browser fires `storage` only in the other tabs of this origin, so the tab that saved is not notified.
export function onLinkTaggingSavedInAnotherTab(callback: () => void): () => void {
    const listener = (event: StorageEvent): void => {
        if (event.key === LINK_TAGGING_SAVED_KEY) {
            callback()
        }
    }
    window.addEventListener('storage', listener)
    return () => window.removeEventListener('storage', listener)
}
