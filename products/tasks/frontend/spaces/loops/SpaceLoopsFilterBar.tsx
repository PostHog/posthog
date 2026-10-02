import { useActions, useValues } from 'kea'
import { ChangeEvent } from 'react'

import { IconCheck, IconSearch } from '@posthog/icons'
import { Button, InputGroup, InputGroupAddon, InputGroupInput } from '@posthog/quill'

import { LoopSelect } from './form/SpaceLoopFormFields'
import { SpaceLoopVisibilityFilter } from './spaceLoopMapping'
import { spaceLoopsLogic } from './spaceLoopsLogic'

export function SpaceLoopsFilterBar({ id }: { id: string }): JSX.Element {
    const { search, hidePaused, visibilityFilter, backend, loops } = useValues(spaceLoopsLogic({ id }))
    const { setSearch, setHidePaused, setVisibilityFilter } = useActions(spaceLoopsLogic({ id }))
    const teamCount = (loops ?? []).filter((loop) => loop.visibility === 'team').length
    const personalCount = (loops ?? []).length - teamCount

    return (
        <div className="flex flex-wrap items-center gap-2">
            {/* Workflow loops are always team-visible, so only the loops API offers the filter. */}
            {backend && !backend.workflowBacked && (
                <LoopSelect<SpaceLoopVisibilityFilter>
                    value={visibilityFilter}
                    options={[
                        { value: 'all', label: 'Team and personal' },
                        { value: 'team', label: `Team loops (${teamCount})` },
                        { value: 'personal', label: `Personal loops (${personalCount})` },
                    ]}
                    onChange={setVisibilityFilter}
                    ariaLabel="Filter by visibility"
                    className="w-48"
                />
            )}
            <InputGroup className="max-w-64">
                <InputGroupInput
                    type="search"
                    placeholder="Search loops"
                    aria-label="Search loops"
                    value={search}
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                    data-attr="today-space-loops-search"
                />
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
            </InputGroup>
            <Button
                size="sm"
                variant={hidePaused ? 'outline' : 'link-muted'}
                aria-pressed={hidePaused}
                onClick={() => setHidePaused(!hidePaused)}
                data-attr="today-space-loops-hide-paused"
            >
                {hidePaused && <IconCheck />}
                <span>Hide paused</span>
            </Button>
        </div>
    )
}
