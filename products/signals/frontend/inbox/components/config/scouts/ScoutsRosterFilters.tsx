import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutTagsFilter } from './ScoutTagsFilter'

export function ScoutsRosterFilters(): JSX.Element {
    const { scoutSearch, scoutEnabledFilter, scoutTagOptions, activeScoutTags } = useValues(scoutFleetLogic)
    const { setScoutSearch, setScoutEnabledFilter, setScoutTagFilter } = useActions(scoutFleetLogic)

    return (
        <div className="ml-auto flex flex-wrap items-center gap-2">
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
                className="w-56"
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
