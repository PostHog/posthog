import { useActions } from 'kea'
import { useState } from 'react'

import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { ReleaseRow } from './releaseUtils'

const SEARCH_LIMIT = 20

export function ReleaseScheduleFlagSearch({ row }: { row: ReleaseRow }): JSX.Element {
    const { openSchedule } = useActions(releaseLogic)
    const [query, setQuery] = useState('')
    const search = query.trim().toLowerCase()
    const matches = row.flags
        .filter((flag) => !search || flag.key.toLowerCase().includes(search))
        .slice(0, SEARCH_LIMIT)
    const keys = new Map(matches.map((flag) => [flag.id, flag.key]))

    return (
        <Combobox
            items={matches.map((flag) => flag.id)}
            filter={null}
            value={null}
            onInputValueChange={setQuery}
            onValueChange={(flagId: number | null) => flagId !== null && openSchedule(flagId)}
            itemToStringLabel={(flagId: number) => keys.get(flagId) ?? ''}
        >
            <ComboboxInput
                placeholder="Schedule a change for a flag"
                aria-label="Schedule a change for a flag"
                data-attr="release-schedule"
            />
            <ComboboxContent>
                <ComboboxEmpty>No linked flag matches that key.</ComboboxEmpty>
                <ComboboxList>
                    {(flagId: number) => (
                        <ComboboxItem key={flagId} value={flagId} data-attr="release-schedule-flag">
                            <span className="font-mono">{keys.get(flagId)}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
