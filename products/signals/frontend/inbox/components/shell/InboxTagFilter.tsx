import { useActions, useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'

// Mirrors the server's slug rules closely enough that a typed tag reads the way it will match.
const toTagSlug = (input: string): string => input.toLowerCase().replace(/[\s_]+/g, '-')

/** Free-form tag filter: type a tag, or click one on a report. Reports with any selected tag stay. */
export function InboxTagFilter(): JSX.Element {
    const { tagFilter } = useValues(inboxFiltersLogic)
    const { setTagFilter } = useActions(inboxFiltersLogic)

    return (
        <LemonInputSelect
            mode="multiple"
            allowCustomValues
            size="small"
            className="min-w-40 max-w-80"
            placeholder="Filter by tag"
            value={tagFilter}
            options={tagFilter.map((tag) => ({ key: tag, label: tag }))}
            inputTransform={toTagSlug}
            onChange={(tags) => setTagFilter(tags.map((tag) => tag.trim()).filter((tag) => tag.length > 0))}
            data-attr="inbox-filter-tag"
        />
    )
}
