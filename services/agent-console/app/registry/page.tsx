/**
 * `/registry` — Tools & Skills landing page.
 *
 * Three tabs:
 *   - **Native tools** — live data from `/agent_native_tools/`.
 *   - **Skills** — live; supports drag-and-drop folder / zip upload.
 *   - **Custom tools** — live data from `/agent_custom_tool_templates/`.
 *
 * Each tab is a searchable list of cards. Click a card to drill into a
 * detail page (separate routes — landing here only). See the plan at
 * `docs/agent-platform/plans/skill-templates.md`.
 */

import { RegistryClient } from './registry-client'

export default function RegistryPage(): React.ReactElement {
    return <RegistryClient />
}
