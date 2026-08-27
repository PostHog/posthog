import { useActions, useValues } from 'kea'
import type { ChangeEvent, ReactNode } from 'react'

import { IconSearch } from '@posthog/icons'

import { InputGroup, InputGroupAddon, InputGroupInput } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { issueFiltersLogic } from './issueFiltersLogic'

export function IssueSearchInput({
    className,
    placeholder = 'Search issues',
    endAddon,
}: {
    className?: string
    placeholder?: string
    endAddon?: ReactNode
}): JSX.Element {
    const { searchInput } = useValues(issueFiltersLogic)
    const { setSearchInput } = useActions(issueFiltersLogic)

    return (
        <div className={cn('w-64 max-w-full shrink-0', className)}>
            <InputGroup className="h-7 border-muted-foreground/20 focus-within:border-ring/50">
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
                {endAddon && (
                    <InputGroupAddon align="inline-end" className="min-w-0 gap-1 px-1 py-0">
                        {endAddon}
                    </InputGroupAddon>
                )}
            </InputGroup>
        </div>
    )
}
