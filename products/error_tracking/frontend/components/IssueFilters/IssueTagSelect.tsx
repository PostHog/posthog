import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconArrowRight, IconSearch } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    MenuLabel,
    Popover,
    PopoverContent,
    PopoverTrigger,
    ScrollArea,
    SelectTriggerIcon,
    Separator,
    Text,
} from 'lib/ui/quill'
import type { SettingId } from 'scenes/settings/types'

import type { ErrorTrackingIssueTagDefinitionApi } from '../../generated/api.schemas'
import { configurationRedirect } from '../../settingsRedirects'
import { type IssueTagState, type IssueTagsFilter, issueTagStateOf } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { IssueTagRow } from './IssueTagRow'

const TAG_RULES_SETTING_ID: SettingId = 'error-tracking-tag-rules'

function buttonText(issueTags: IssueTagsFilter | null, labelOf: (key: string) => string): string {
    if (!issueTags) {
        return 'Any tag'
    }
    const count = issueTags.has.length + issueTags.hasNot.length
    if (count > 1) {
        return `${count} tags`
    }
    return issueTags.has.length ? `Tags: ${labelOf(issueTags.has[0])}` : `Tags: not ${labelOf(issueTags.hasNot[0])}`
}

// The name holds the visible text unchanged, so a voice control user can press the button by saying what it shows.
function ariaLabel(issueTags: IssueTagsFilter | null, labelOf: (key: string) => string): string {
    const label = `Tag filter: ${buttonText(issueTags, labelOf)}`
    if (!issueTags || issueTags.has.length + issueTags.hasNot.length < 2) {
        return label
    }
    const parts: string[] = [label]
    if (issueTags.has.length) {
        parts.push(`has ${issueTags.has.map(labelOf).join(' and ')}`)
    }
    if (issueTags.hasNot.length) {
        parts.push(`not ${issueTags.hasNot.map(labelOf).join(' or ')}`)
    }
    return parts.join(', ')
}

export function IssueTagSelect({
    definitions,
    loading,
    issueTags,
    onTagStateChange,
    onClear,
}: {
    definitions: Pick<ErrorTrackingIssueTagDefinitionApi, 'key' | 'label' | 'description'>[]
    loading: boolean
    issueTags: IssueTagsFilter | null
    onTagStateChange: (key: string, state: IssueTagState | null) => void
    onClear: () => void
}): JSX.Element {
    const { searchParams } = useValues(router)
    const [search, setSearch] = useState('')
    // The tags selected when the list opens go to the top. They keep their place while it is open, so a row does not
    // move away from the pointer when it is clicked.
    const [topKeys, setTopKeys] = useState<string[]>([])
    const labelOf = (key: string): string => definitions.find((definition) => definition.key === key)?.label ?? key
    const query = search.trim().toLowerCase()
    const matchingDefinitions = query
        ? definitions.filter((definition) => definition.label.toLowerCase().includes(query))
        : definitions
    const topDefinitions = matchingDefinitions.filter((definition) => topKeys.includes(definition.key))
    const otherDefinitions = matchingDefinitions.filter((definition) => !topKeys.includes(definition.key))
    const row = (definition: (typeof definitions)[number]): JSX.Element => (
        <IssueTagRow
            key={definition.key}
            definition={definition}
            state={issueTagStateOf(issueTags, definition.key)}
            onChange={(state) => onTagStateChange(definition.key, state)}
        />
    )

    return (
        <Popover
            onOpenChange={(open: boolean) => {
                if (open) {
                    setTopKeys(issueTags ? [...issueTags.has, ...issueTags.hasNot] : [])
                }
            }}
            // The popup stays on screen while it fades out, so clearing the search any earlier shows the full list then.
            onOpenChangeComplete={(open: boolean) => {
                if (!open) {
                    setSearch('')
                }
            }}
        >
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="default"
                        loading={loading}
                        aria-label={ariaLabel(issueTags, labelOf)}
                        data-attr="error-tracking-issue-tag-filter"
                    />
                }
            >
                <span className="max-w-48 truncate">{buttonText(issueTags, labelOf)}</span>
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-80 gap-1 p-1" aria-label="Tag filter">
                <InputGroup size="sm">
                    <InputGroupAddon align="inline-start">
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        aria-label="Search tags"
                        placeholder="Search tags"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                    />
                </InputGroup>
                {/* The scrollbar shows over the list, so a list that scrolls keeps its buttons clear of it. */}
                <ScrollArea viewportClassName="max-h-80 group-data-[has-overflow-y]/scroll-area:pe-2.5">
                    {matchingDefinitions.length ? (
                        <>
                            {topDefinitions.length > 0 && <MenuLabel className="pt-1.5">Selected tags</MenuLabel>}
                            {topDefinitions.map(row)}
                            {topDefinitions.length > 0 && otherDefinitions.length > 0 && (
                                <MenuLabel className="pt-2">Other tags</MenuLabel>
                            )}
                            {otherDefinitions.map(row)}
                        </>
                    ) : (
                        <Text size="xs" variant="muted" className="px-2 py-1.5">
                            No matching tags
                        </Text>
                    )}
                </ScrollArea>
                <Separator />
                <div className="flex items-center gap-2">
                    {issueTags && (
                        <Button
                            variant="default"
                            size="sm"
                            data-attr="error-tracking-issue-tag-filter-clear"
                            onClick={() => {
                                setTopKeys([])
                                onClear()
                            }}
                        >
                            Clear all
                        </Button>
                    )}
                    <Button
                        variant="default"
                        size="sm"
                        className="ml-auto"
                        data-attr="error-tracking-issue-tag-filter-manage-rules"
                        // configurationRedirect keeps the search params, which hold the list filters, so opening the rules
                        // does not reset them.
                        render={<LinkPrimitive to={configurationRedirect(TAG_RULES_SETTING_ID, searchParams, {})} />}
                    >
                        Manage tag rules
                        <IconArrowRight />
                    </Button>
                </div>
            </PopoverContent>
        </Popover>
    )
}
