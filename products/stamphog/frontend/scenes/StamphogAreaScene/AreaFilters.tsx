import { useActions, useValues } from 'kea'

import { LemonInputSelect, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { AREA_FILTER_OPTIONS, AREA_WINDOW_OPTIONS } from './areaDisplay'
import { stamphogAreaSceneLogic } from './stamphogAreaSceneLogic'

export function AreaFilters(): JSX.Element {
    const { owner, owners, ownersLoading, filter, windowDays } = useValues(stamphogAreaSceneLogic)
    const { setOwner, setFilter, setWindowDays } = useActions(stamphogAreaSceneLogic)

    return (
        <div className="flex gap-2 flex-wrap items-center">
            <div className="w-72">
                <LemonInputSelect
                    mode="single"
                    value={owner ? [owner] : []}
                    onChange={(values) => setOwner(values[0] ?? '')}
                    options={owners.map((entry) => ({
                        key: entry.owner,
                        label: `${entry.owner} · ${pluralize(entry.pr_count, 'PR')}`,
                    }))}
                    loading={ownersLoading}
                    placeholder="Pick your team"
                    data-attr="stamphog-area-team"
                />
            </div>
            <LemonSegmentedButton
                value={filter}
                onChange={setFilter}
                options={AREA_FILTER_OPTIONS.map((option) => ({
                    ...option,
                    'data-attr': `stamphog-area-filter-${option.value}`,
                }))}
                size="small"
            />
            <LemonSelect
                value={windowDays}
                onChange={setWindowDays}
                options={AREA_WINDOW_OPTIONS}
                size="small"
                data-attr="stamphog-area-window"
            />
        </div>
    )
}
