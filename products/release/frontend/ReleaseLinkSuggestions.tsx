import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Button, Text } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { linkSuggestionsKey, releaseLogic } from './releaseLogic'
import { ReleaseRow } from './releaseUtils'

export function ReleaseLinkSuggestions({ row }: { row: ReleaseRow }): JSX.Element | null {
    const { linkSuggestions: loaded, linkSuggestionsFor } = useValues(releaseLogic)
    const { loadLinkSuggestions, addLink } = useActions(releaseLogic)

    useEffect(() => {
        loadLinkSuggestions(row.id)
    }, [row.id, row.name, loadLinkSuggestions])

    const linkSuggestions = linkSuggestionsFor === linkSuggestionsKey(row) ? loaded : []
    if (!linkSuggestions.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-1.5" data-attr="release-link-suggestions">
            <Text size="xxs" weight="semibold" variant="muted" className="uppercase tracking-wide">
                Looks related
            </Text>
            {linkSuggestions.map((candidate) => (
                <div key={candidate.key} className="flex min-w-0 items-center gap-2">
                    <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4">
                        {iconForType(candidate.kind === 'flag' ? 'feature_flag' : 'broadcasts')}
                    </span>
                    <Text
                        size="xs"
                        className={
                            candidate.kind === 'flag' ? 'min-w-0 flex-1 truncate font-mono' : 'min-w-0 flex-1 truncate'
                        }
                    >
                        {candidate.label}
                    </Text>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => addLink(row.id, candidate)}
                        data-attr="release-link-suggestion-add"
                    >
                        Add
                    </Button>
                </div>
            ))}
        </div>
    )
}
