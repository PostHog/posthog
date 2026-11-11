import { useActions, useValues } from 'kea'

import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { ReleaseRow } from './releaseUtils'

export function ReleaseLinkFlagCombobox({ row, placeholder }: { row: ReleaseRow; placeholder?: string }): JSX.Element {
    const { flags } = useValues(releaseLogic)
    const { linkFlag } = useActions(releaseLogic)
    const linked = new Set(row.flags.map((flag) => flag.id))
    const candidates = flags.filter((flag) => !linked.has(flag.id))
    const keys = new Map(candidates.map((flag) => [flag.id, flag.key]))

    return (
        <Combobox
            items={candidates.map((flag) => flag.id)}
            value={null}
            onValueChange={(flagId: number | null) => flagId !== null && linkFlag(row.id, flagId)}
            itemToStringLabel={(flagId: number) => keys.get(flagId) ?? ''}
        >
            <ComboboxInput
                placeholder={placeholder ?? 'Link a flag'}
                aria-label="Link a feature flag"
                data-attr="release-link-flag"
            />
            <ComboboxContent>
                <ComboboxEmpty>No flag matches that key.</ComboboxEmpty>
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
