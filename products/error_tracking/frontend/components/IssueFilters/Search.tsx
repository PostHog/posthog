import { useActions, useValues } from 'kea'
import type { ChangeEvent } from 'react'

import { IconSearch } from '@posthog/icons'

import { InputGroup, InputGroupAddon, InputGroupInput } from 'lib/ui/quill'

import { issueFiltersLogic } from './issueFiltersLogic'

export function IssueSearchInput({ placeholder = 'Search issues' }: { placeholder?: string }): JSX.Element {
    const { searchInput } = useValues(issueFiltersLogic)
    const { setSearchInput } = useActions(issueFiltersLogic)

    return (
        <div className="w-64 max-w-full shrink-0">
            <InputGroup className="h-7">
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    value={searchInput}
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setSearchInput(event.target.value)}
                    placeholder={placeholder}
                    aria-label={placeholder}
                />
            </InputGroup>
        </div>
    )
}
