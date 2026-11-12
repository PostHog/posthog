import { useActions, useValues } from 'kea'

import {
    Button,
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

export function ReleaseLinkFlagCombobox({ row, placeholder }: { row: ReleaseRow; placeholder?: string }): JSX.Element {
    const { flagSearchResults, flagSearchResultsLoading, flagSearch, flagSearchFailed } = useValues(releaseLogic)
    const { linkFlag, searchFlags } = useActions(releaseLogic)
    const linked = new Set(row.flags.map((flag) => flag.id))
    const candidates = flagSearchResults.filter((flag) => !linked.has(flag.id) && !flag.archived)
    const keys = new Map(candidates.map((flag) => [flag.id, flag.key]))

    return (
        <Combobox
            items={candidates.map((flag) => flag.id)}
            filter={null}
            value={null}
            onOpenChange={(open: boolean) => open && searchFlags('')}
            onInputValueChange={(value: string) => searchFlags(value)}
            onValueChange={(flagId: number | null) => flagId !== null && linkFlag(row.id, flagId)}
            itemToStringLabel={(flagId: number) => keys.get(flagId) ?? ''}
        >
            <ComboboxInput
                placeholder={placeholder ?? 'Link a flag'}
                aria-label="Link a feature flag"
                data-attr="release-link-flag"
            />
            <ComboboxContent>
                {flagSearchFailed && (
                    <div className="flex items-center justify-between gap-2 p-2 text-xs">
                        <span>The flags could not load.</span>
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={() => searchFlags(flagSearch)}
                            data-attr="release-link-flag-retry"
                        >
                            Try again
                        </Button>
                    </div>
                )}
                <ComboboxEmpty>
                    {flagSearchFailed ? null : flagSearchResultsLoading ? <Spinner /> : 'No flag matches that key.'}
                </ComboboxEmpty>
                <ComboboxList>
                    {(flagId: number) => (
                        <ComboboxItem key={flagId} value={flagId} data-attr="release-link-flag-option">
                            <span className="font-mono">{keys.get(flagId)}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
