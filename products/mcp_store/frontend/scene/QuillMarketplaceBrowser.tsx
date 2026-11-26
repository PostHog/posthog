import { useActions, useValues } from 'kea'

import { IconPlus, IconSearch } from '@posthog/icons'
import {
    Button,
    CardGroup,
    DropdownMenu,
    DropdownMenuContent,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
    Heading,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
} from '@posthog/quill'

import type { MCPServerTemplateApi } from '../generated/api.schemas'
import { mcpStoreLogic } from '../mcpStoreLogic'
import { QuillInstalledServersList } from './QuillInstalledServersList'
import { ServerCard } from './ServerCard'

const ALL_CATEGORIES = 'all'

export function QuillMarketplaceBrowser({
    categoryOptions,
    groups,
    restrictedReason,
}: {
    categoryOptions: FilterOption[]
    groups: Array<{ value: string; label: string; servers: MCPServerTemplateApi[] }>
    restrictedReason: string | null
}): JSX.Element {
    const { searchQuery, categoryFilter } = useValues(mcpStoreLogic)
    const { setSearchQuery, setCategoryFilter, openAddCustomServerModal } = useActions(mcpStoreLogic)

    const filterActive = categoryFilter !== ALL_CATEGORIES

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <InputGroup size="sm" className="min-w-48 flex-1">
                    <InputGroupAddon align="inline-start">
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        placeholder="Search..."
                        aria-label="Search MCP servers"
                        value={searchQuery}
                        onChange={(event) => setSearchQuery(event.target.value)}
                    />
                </InputGroup>
                <DropdownMenu>
                    <FilterMenuTrigger active={filterActive} />
                    <DropdownMenuContent align="start" className="min-w-64">
                        <FilterRadioSubMenu
                            label="Category"
                            options={categoryOptions}
                            value={categoryFilter}
                            defaultValue={ALL_CATEGORIES}
                            onChange={setCategoryFilter}
                        />
                        <FilterClearItem active={filterActive} onClear={() => setCategoryFilter(ALL_CATEGORIES)} />
                    </DropdownMenuContent>
                </DropdownMenu>
                <Button variant="primary" onClick={() => openAddCustomServerModal()} disabledReason={restrictedReason}>
                    <IconPlus />
                    Add server
                </Button>
            </div>
            <QuillInstalledServersList />
            {groups.map((group) => (
                <section key={group.value} className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        {group.label}
                    </Heading>
                    <CardGroup size="sm">
                        {group.servers.map((server) => (
                            <ServerCard key={server.id} server={server} />
                        ))}
                    </CardGroup>
                </section>
            ))}
        </div>
    )
}
