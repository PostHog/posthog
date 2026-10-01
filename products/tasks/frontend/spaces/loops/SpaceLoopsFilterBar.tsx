import { useActions, useValues } from 'kea'
import { ChangeEvent } from 'react'

import { IconCheck, IconSearch } from '@posthog/icons'
import { Button, InputGroup, InputGroupAddon, InputGroupInput, Text } from '@posthog/quill'

import { spaceLoopsLogic } from './spaceLoopsLogic'

export function SpaceLoopsFilterBar({ id }: { id: string }): JSX.Element {
    const { search, hidePaused, activeCount } = useValues(spaceLoopsLogic({ id }))
    const { setSearch, setHidePaused } = useActions(spaceLoopsLogic({ id }))

    return (
        <div className="flex flex-wrap items-center gap-2">
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
                variant={hidePaused ? 'outline' : 'link-muted'}
                aria-pressed={hidePaused}
                onClick={() => setHidePaused(!hidePaused)}
                data-attr="today-space-loops-hide-paused"
            >
                {hidePaused && <IconCheck />}
                Hide paused
            </Button>
            <Text render={<span />} size="xs" variant="muted" className="ml-auto">
                {`${activeCount} active`}
            </Text>
        </div>
    )
}
