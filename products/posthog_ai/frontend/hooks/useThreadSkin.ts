import type { ThreadSkin } from '../components/quill/quillThreadContext'

/**
 * The skin for every PostHog AI chat surface: the thread, the run composer and its pickers. Hardcoded to
 * quill while `phai-quill` is rolled out; restore the `PHAI_QUILL` / `TODAY_RAIL_NAV` flag check to gate it.
 */
export function useThreadSkin(): ThreadSkin {
    return 'quill'
}
