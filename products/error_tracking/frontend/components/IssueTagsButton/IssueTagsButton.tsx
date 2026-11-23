import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'

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
} from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'
import type { SettingId } from 'scenes/settings/types'

import type { ErrorTrackingIssueTag } from '~/queries/schema/schema-general'

import { configurationRedirect } from '../../settingsRedirects'
import { issueTagRuleKeysLogic } from './issueTagRuleKeysLogic'

const TAG_RULES_SETTING_ID: SettingId = 'error-tracking-tag-rules'

export function IssueTagsButton({
    tags,
    onTagClick,
    size = 'sm',
}: {
    tags: Pick<ErrorTrackingIssueTag, 'key' | 'label'>[] | null | undefined
    onTagClick: (key: string) => void
    size?: 'sm' | 'default'
}): JSX.Element | null {
    const { searchParams } = useValues(router)
    const { issueTagRuleKeys } = useValues(issueTagRuleKeysLogic)
    const [open, setOpen] = useState(false)

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
            <PopoverContent align="start" className="w-56 p-1" aria-label="Issue tags">
                {/* The scrollbar shows over the list, so a list that scrolls keeps its buttons clear of it. */}
                <ScrollArea viewportClassName="max-h-80 group-data-[has-overflow-y]/scroll-area:pe-2.5">
                    {tags.map((tag) => (
                        <div key={tag.key} className="flex items-center gap-1 rounded-sm px-1 hover:bg-fill-hover">
                            <Item
                                variant="menuItem"
                                size="xs"
                                render={<button type="button" />}
                                className="min-w-0 flex-1 p-0 text-left hover:bg-transparent"
                                aria-label={`Show issues tagged ${tag.label}`}
                                data-attr="error-tracking-issue-tags-button-tag"
                                onClick={() => {
                                    setOpen(false)
                                    onTagClick(tag.key)
                                }}
                            >
                                <ItemContent variant="menuItem" className="min-w-0">
                                    <ItemTitle className="block w-full min-w-0 truncate font-normal">
                                        {tag.label}
                                    </ItemTitle>
                                </ItemContent>
                            </Item>
                            {issueTagRuleKeys?.includes(tag.key) && (
                                <Button
                                    variant="default"
                                    size="icon-sm"
                                    tooltip="Manage tag rules"
                                    aria-label="Manage tag rules"
                                    data-attr="error-tracking-issue-tags-button-manage-rules"
                                    // configurationRedirect keeps the search params, which hold the list filters, so
                                    // opening the rules does not reset them.
                                    render={
                                        <LinkPrimitive
                                            to={configurationRedirect(TAG_RULES_SETTING_ID, searchParams, {})}
                                        />
                                    }
                                >
                                    <IconGear />
                                </Button>
                            )}
                        </div>
                    ))}
                </ScrollArea>
            </PopoverContent>
        </Popover>
    )
}
