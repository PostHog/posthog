import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import type { MCPServerTemplateApi } from '../generated/api.schemas'
import { mcpStoreLogic } from '../mcpStoreLogic'
import { InstalledServersList } from './InstalledServersList'
import { ServerCard } from './ServerCard'

// "All" + the CATEGORY_CHOICES on MCPServerTemplate, in alphabetical order to
// match Django.
const CATEGORY_OPTIONS = [
    { value: 'all', label: 'All' },
    { value: 'business', label: 'Business Operations' },
    { value: 'data', label: 'Data & Analytics' },
    { value: 'design', label: 'Design & Content' },
    { value: 'dev', label: 'Developer Tools & APIs' },
    { value: 'infra', label: 'Infrastructure' },
    { value: 'productivity', label: 'Productivity & Collaboration' },
]

// Category order for groupings, excluding the synthetic "All" bucket. Anything
// returned by the API without a known category falls through to "dev" (the
// same default used by the backend).
const CATEGORY_ORDER: Array<{ value: string; label: string }> = CATEGORY_OPTIONS.filter((o) => o.value !== 'all')
const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(CATEGORY_ORDER.map((o) => [o.value, o.label]))

function groupByCategory(
    servers: MCPServerTemplateApi[]
): Array<{ value: string; label: string; servers: MCPServerTemplateApi[] }> {
    const buckets = new Map<string, MCPServerTemplateApi[]>()
    for (const server of servers) {
        const key = server.category && CATEGORY_LABEL[server.category] ? server.category : 'dev'
        if (!buckets.has(key)) {
            buckets.set(key, [])
        }
        buckets.get(key)!.push(server)
    }
    return CATEGORY_ORDER.filter((c) => buckets.has(c.value)).map((c) => ({
        value: c.value,
        label: c.label,
        servers: buckets.get(c.value)!,
    }))
}

export function MarketplaceBrowser(): JSX.Element {
    const { filteredServers, searchQuery, categoryFilter } = useValues(mcpStoreLogic)
    const { setSearchQuery, setCategoryFilter, openAddCustomServerModal } = useActions(mcpStoreLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    const grouped = groupByCategory(filteredServers)

    return (
        <div className="deprecated-space-y-4">
            <div className="flex items-center gap-2">
                <div className="flex-1 min-w-0">
                    <LemonInput
                        type="search"
                        placeholder="Search..."
                        value={searchQuery}
                        onChange={setSearchQuery}
                        fullWidth
                    />
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => openAddCustomServerModal()}
                    disabledReason={restrictedReason}
                >
                    Add server
                </LemonButton>
            </div>

            <div className="flex gap-6 items-start">
                <aside className="w-56 flex-shrink-0">
                    <nav className="flex flex-col gap-0.5">
                        {CATEGORY_OPTIONS.map((option) => {
                            const isActive = categoryFilter === option.value
                            return (
                                <button
                                    key={option.value}
                                    onClick={() => setCategoryFilter(option.value)}
                                    className={`text-left text-sm px-3 py-2 rounded transition-colors ${
                                        isActive
                                            ? 'bg-accent-highlight-secondary text-accent font-medium'
                                            : 'text-default hover:bg-surface-secondary'
                                    }`}
                                >
                                    {option.label}
                                </button>
                            )
                        })}
                    </nav>
                </aside>

                <div className="flex-1 min-w-0 deprecated-space-y-4">
                    <InstalledServersList />

                    <div className="deprecated-space-y-6">
                        {grouped.map((group) => (
                            <section key={group.value} className="deprecated-space-y-2">
                                <h2 className="mb-0 text-base font-semibold">{group.label}</h2>
                                <div className="grid grid-cols-1 gap-3">
                                    {group.servers.map((server) => (
                                        <ServerCard key={server.id} server={server} />
                                    ))}
                                </div>
                            </section>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
