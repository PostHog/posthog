import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    Button,
    Item,
    ItemContent,
    ItemTitle,
    Popover,
    PopoverContent,
    PopoverTrigger,
    ScrollArea,
    SelectTriggerIcon,
    Separator,
} from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'
import type { SettingId } from 'scenes/settings/types'

import type { ErrorTrackingIssueTag } from '~/queries/schema/schema-general'

import { configurationRedirect } from '../../settingsRedirects'

const TAG_RULES_SETTING_ID: SettingId = 'error-tracking-tag-rules'

export function IssueTagsButton({
    tags,
    onTagClick,
    size = 'sm',
    defaultOpen = false,
}: {
    tags: Pick<ErrorTrackingIssueTag, 'key' | 'label'>[] | null | undefined
    onTagClick: (key: string) => void
    size?: 'sm' | 'default'
    defaultOpen?: boolean
}): JSX.Element | null {
    const { searchParams } = useValues(router)
    const [open, setOpen] = useState(defaultOpen)

    if (!tags?.length) {
        return null
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={<Button variant="outline" size={size} data-attr="error-tracking-issue-tags-button" />}
            >
                <span className="text-secondary">{pluralize(tags.length, 'tag')}</span>
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-56 gap-1 p-1" aria-label="Issue tags">
                {/* The scrollbar shows over the list, so a list that scrolls keeps its buttons clear of it. */}
                <ScrollArea viewportClassName="max-h-80 group-data-[has-overflow-y]/scroll-area:pe-2.5">
                    <div role="list">
                        {tags.map((tag) => (
                            <div key={tag.key} role="listitem" className="rounded-sm px-1 hover:bg-fill-hover">
                                <Item
                                    variant="menuItem"
                                    size="xs"
                                    render={<button type="button" />}
                                    className="w-full min-w-0 p-0 text-left hover:bg-transparent"
                                    aria-label={`Show issues tagged ${tag.label}`}
                                    data-attr="error-tracking-issue-tags-button-tag"
                                    onClick={() => {
                                        setOpen(false)
                                        onTagClick(tag.key)
                                    }}
                                >
                                    <ItemContent variant="menuItem" className="min-w-0">
                                        <ItemTitle
                                            className="block w-full min-w-0 truncate font-normal"
                                            title={tag.label}
                                        >
                                            {tag.label}
                                        </ItemTitle>
                                    </ItemContent>
                                </Item>
                            </div>
                        ))}
                    </div>
                </ScrollArea>
                <Separator />
                <Button
                    variant="default"
                    size="sm"
                    className="ml-auto"
                    data-attr="error-tracking-issue-tags-button-manage-rules"
                    // configurationRedirect keeps the search params, which hold the list filters, so opening the rules
                    // does not reset them.
                    render={<LinkPrimitive to={configurationRedirect(TAG_RULES_SETTING_ID, searchParams, {})} />}
                >
                    Manage tag rules
                    <IconArrowRight />
                </Button>
            </PopoverContent>
        </Popover>
    )
}
