import { useActions, useValues } from 'kea'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
    Text,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'
import { AnalyticsTagIcon } from 'scenes/analytics/AnalyticsTagIcon'

import { EndpointType } from '~/types'

import { endpointsLogic } from './endpointsLogic'

/** A row's tags as one chip, like the Analytics list: the tag the list is filtered by, or the count, with the rest in a menu. */
export function QuillEndpointTagsChip({ endpoint }: { endpoint: EndpointType }): JSX.Element | null {
    const { filters } = useValues(endpointsLogic)
    const { setFilters } = useActions(endpointsLogic)
    const tags = [...(endpoint.tags ?? [])].sort()
    if (tags.length === 0) {
        return null
    }

    const filtered = tags.find((tag) => filters.tags.includes(tag))
    const toggle = (tag: string): void =>
        setFilters({
            tags: filters.tags.includes(tag) ? filters.tags.filter((other) => other !== tag) : [...filters.tags, tag],
        })

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="xs"
                        aria-label={`${pluralize(tags.length, 'tag')} on ${endpoint.name}`}
                        className="max-w-48 shrink-0 gap-1 px-1.5"
                        data-attr="endpoint-row-tags"
                    />
                }
            >
                <AnalyticsTagIcon />
                {filtered ? (
                    <>
                        <span className="min-w-0 truncate">{filtered}</span>
                        {tags.length > 1 && (
                            <span className="shrink-0 text-muted-foreground">{`+${tags.length - 1}`}</span>
                        )}
                    </>
                ) : (
                    <span>{tags.length}</span>
                )}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56 max-w-80">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>{pluralize(tags.length, 'tag')}</DropdownMenuLabel>
                    {tags.map((tag) => {
                        const active = filters.tags.includes(tag)
                        return (
                            <DropdownMenuItem key={tag} onClick={() => toggle(tag)} data-attr="endpoint-row-tag">
                                <AnalyticsTagIcon className="size-3.5" />
                                <span className="min-w-0 flex-1 break-all text-left">{tag}</span>
                                <Text size="xs" variant="muted" className="ml-2 shrink-0">
                                    {active ? 'Remove filter' : 'Filter'}
                                </Text>
                            </DropdownMenuItem>
                        )
                    })}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
