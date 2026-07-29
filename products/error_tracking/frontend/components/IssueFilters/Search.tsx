import { useActions, useValues } from 'kea'
import type { ChangeEvent } from 'react'

import { IconSearch } from '@posthog/icons'

import { InputGroup, InputGroupAddon, InputGroupInput } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { issueFiltersLogic } from './issueFiltersLogic'

export function IssueSearchInput({
    className,
    placeholder = 'Search issues',
}: {
    className?: string
    placeholder?: string
}): JSX.Element {
    const { searchInput } = useValues(issueFiltersLogic)
    const { setSearchInput } = useActions(issueFiltersLogic)

    return (
        <div className={cn('w-64 max-w-full shrink-0', className)}>
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
