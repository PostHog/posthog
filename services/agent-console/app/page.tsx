/**
 * `/` — overview landing page.
 *
 * Leads with an embedded concierge chat so users can start talking
 * immediately. The agents list lives under `/agents` now.
 */

import { OverviewClient } from './overview-client'

export default function HomePage(): React.ReactElement {
    return <OverviewClient />
}
