import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutTagsFilter } from './ScoutTagsFilter'

export function ScoutsRosterFilters({ compact }: { compact: boolean }): JSX.Element {
    const { scoutSearch, scoutEnabledFilter, scoutTagOptions, activeScoutTags } = useValues(scoutFleetLogic)
    const { setScoutSearch, setScoutEnabledFilter, setScoutTagFilter } = useActions(scoutFleetLogic)

    return (
        // Compact takes the whole line rather than being pushed right: at phone widths the filters
        // never share a row with the stats anyway, and a right-hugging half-row just wastes it.
        <div className={cn('flex flex-wrap items-center gap-2', compact ? 'w-full' : 'ml-auto')}>
            <LemonSegmentedButton
                size="small"
                value={scoutEnabledFilter}
                onChange={setScoutEnabledFilter}
                options={[
                    { value: 'all', label: 'All' },
                    { value: 'enabled', label: 'On' },
                    { value: 'disabled', label: 'Off' },
                ]}
            />
            <LemonInput
                type="search"
                size="small"
                placeholder="Search scouts…"
                value={scoutSearch}
                onChange={setScoutSearch}
                className={compact ? 'min-w-32 flex-1' : 'w-56'}
                allowClear
            />
            {scoutTagOptions.length > 0 && (
                <>
                    <ScoutTagsFilter
                        options={scoutTagOptions}
                        selected={activeScoutTags}
                        onToggle={(tag) =>
                            setScoutTagFilter(
                                activeScoutTags.includes(tag)
                                    ? activeScoutTags.filter((candidate) => candidate !== tag)
                                    : [...activeScoutTags, tag]
                            )
                        }
                        onClear={() => setScoutTagFilter([])}
                    />
                </>
            )}
        </div>
    )
}
