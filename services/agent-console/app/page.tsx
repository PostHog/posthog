/**
 * `/` — agents list landing page.
 *
 * Shell only — all data fetching happens client-side via the typed
 * `apiClient`, so the same code path runs in dev / prod / Storybook
 * (Storybook intercepts via MSW; prod hits the real backend).
 */

import { AgentsListClient } from './agents-list-client'

export default function HomePage(): React.ReactElement {
    return <AgentsListClient />
}
