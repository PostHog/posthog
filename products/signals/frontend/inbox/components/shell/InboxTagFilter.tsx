import { useActions, useValues } from 'kea'
import { useCallback, useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { TagSelect } from 'lib/components/TagSelect'
import type { LoadTags } from 'lib/components/tagSelectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { signalsReportsTagOptionsRetrieve } from '../../../generated/api'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'

/**
 * Multi-select Tags filter for the Reports list. The options are the team's most-used report tags,
 * fetched once per mount and searched in place. A report matches when it carries any selected tag.
 */
export function InboxTagFilter(): JSX.Element {
    const { tagFilter } = useValues(inboxFiltersLogic)
    const { setTagFilter } = useActions(inboxFiltersLogic)
    const { currentTeamId } = useValues(teamLogic)
    const optionsRef = useRef<Promise<string[]> | null>(null)

    const loadTags = useCallback<LoadTags>(
        async (search) => {
            if (!optionsRef.current) {
                optionsRef.current = signalsReportsTagOptionsRetrieve(String(currentTeamId)).then(({ tags }) => tags)
                // A failed load is retried from the menu, so it must not stay cached.
                optionsRef.current.catch(() => {
                    optionsRef.current = null
                })
            }
            const query = search.trim().toLowerCase()
            const tags = await optionsRef.current
            return { results: tags.filter((tag) => tag.includes(query)).map((tag) => ({ tag })), hasMore: false }
        },
        [currentTeamId]
    )

    return (
        <TagSelect value={tagFilter} onChange={setTagFilter} loadTags={loadTags} logicKey="inbox-tag-filter">
            {(selected) => (
                <LemonButton
                    size="small"
                    type="secondary"
                    active={selected.length > 0}
                    aria-label={selected.length > 0 ? `Tags: ${selected.join(', ')}` : 'Tags: any'}
                    data-attr="inbox-filter-tags"
                >
                    {selected.length > 0 ? `Tags · ${selected.length}` : 'Tags'}
                </LemonButton>
            )}
        </TagSelect>
    )
}
