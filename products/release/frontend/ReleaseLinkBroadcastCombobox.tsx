import { useActions, useValues } from 'kea'

import {
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Spinner,
} from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { ReleaseRow } from './releaseUtils'

export function ReleaseLinkBroadcastCombobox({ row }: { row: ReleaseRow }): JSX.Element {
    const { broadcastSearchResults, broadcastSearchResultsLoading } = useValues(releaseLogic)
    const { linkBroadcast, searchBroadcasts } = useActions(releaseLogic)
    const linked = new Set(row.broadcasts.map((broadcast) => broadcast.id))
    const candidates = broadcastSearchResults.filter((broadcast) => !linked.has(broadcast.id))
    const names = new Map(candidates.map((broadcast) => [broadcast.id, broadcast.name || 'Untitled broadcast']))

    return (
        <Combobox
            items={candidates.map((broadcast) => broadcast.id)}
            filter={null}
            value={null}
            onOpenChange={(open: boolean) => open && searchBroadcasts('')}
            onInputValueChange={(value: string) => searchBroadcasts(value)}
            onValueChange={(broadcastId: string | null) => broadcastId !== null && linkBroadcast(row.id, broadcastId)}
            itemToStringLabel={(broadcastId: string) => names.get(broadcastId) ?? ''}
        >
            <ComboboxInput
                placeholder="Link a broadcast"
                aria-label="Link a broadcast"
                data-attr="release-link-broadcast"
            />
            <ComboboxContent>
                <ComboboxEmpty>
                    {broadcastSearchResultsLoading ? <Spinner /> : 'No broadcast matches that name.'}
                </ComboboxEmpty>
                <ComboboxList>
                    {(broadcastId: string) => (
                        <ComboboxItem key={broadcastId} value={broadcastId} data-attr="release-link-broadcast-option">
                            {names.get(broadcastId)}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
