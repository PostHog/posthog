/**
 * `/registry` — Tools & Skills landing page.
 *
 * Three tabs:
 *   - **Native tools** — live data from `/agent_native_tools/`.
 *   - **Skills** — mocked until the `agent_skill_template` table lands.
 *   - **Custom tools** — mocked until `agent_custom_tool_template` lands.
 *
 * Each tab is a searchable list of cards. Click a card to drill into a
 * detail page (separate routes — landing here only).
 */

import { RegistryClient } from './registry-client'

export default function RegistryPage(): React.ReactElement {
    return <RegistryClient />
}
