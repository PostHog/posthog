import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight, IconList, IconListTree } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { tracingConfigLogic } from './tracingConfigLogic'
import { tracingFiltersLogic, type TracingViewMode } from './tracingFiltersLogic'
import { tracingSceneLogic } from './tracingSceneLogic'

/**
 * The bar above the results, mirroring logs' LogsDisplayBar, grouped by scope:
 *
 *  - persistent-left "frame": controls that apply to the whole results region — the facet
 *    rail toggle, the Traces ⇄ Operations view switch, and the matching-count indicator.
 *  - contextual-right: traces-view-only controls (Traces ⇄ Spans granularity, Compare),
 *    hidden entirely on the Operations view where neither applies.
 */
export function TracingDisplayBar(): JSX.Element {
    const { activeTracingTab, totalMatchingFilters, filters } = useValues(tracingSceneLogic())
    const { setActiveTracingTab } = useActions(tracingSceneLogic())
    const { setViewMode, setCompareMode } = useActions(tracingFiltersLogic())
    const { featureFlags } = useValues(featureFlagLogic)
    const { facetRailCollapsed } = useValues(tracingConfigLogic)
    const { setFacetRailCollapsed } = useActions(tracingConfigLogic)

    const facetRailEnabled = !!featureFlags[FEATURE_FLAGS.TRACING_FACET_RAIL]
    const operationsViewEnabled = !!featureFlags[FEATURE_FLAGS.TRACING_OPERATIONS_VIEW]
    const inTracesView = !operationsViewEnabled || activeTracingTab !== 'operations'
    const showCount = inTracesView && !filters.compareMode && totalMatchingFilters > 0

    return (
        <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
                {facetRailEnabled && (
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={facetRailCollapsed ? <IconChevronRight /> : <IconChevronLeft />}
                        onClick={() => setFacetRailCollapsed(!facetRailCollapsed)}
                        aria-label={facetRailCollapsed ? 'Show facets' : 'Hide facets'}
                        tooltip={facetRailCollapsed ? 'Show facets' : 'Hide facets'}
                        data-attr="tracing-facet-rail-toggle"
                    />
                )}
                {operationsViewEnabled && (
                    <LemonSegmentedButton<'traces' | 'operations'>
                        size="small"
                        value={activeTracingTab}
                        onChange={setActiveTracingTab}
                        options={[
                            { value: 'traces', label: 'Traces', 'data-attr': 'tracing-display-tab-traces' },
                            {
                                value: 'operations',
                                label: 'Operations',
                                'data-attr': 'tracing-display-tab-operations',
                            },
                        ]}
                    />
                )}
                {/* No loading guard: keep the last (view-mode-independent) count visible across reloads,
                    so a Traces/Spans switch doesn't flicker the label out and back in. */}
                {showCount && (
                    <span className="text-muted text-xs">
                        {humanFriendlyNumber(totalMatchingFilters)} {filters.viewMode === 'spans' ? 'spans' : 'traces'}{' '}
                        matching filters
                    </span>
                )}
            </div>
            {inTracesView && (
                <div className="flex items-center gap-1.5 flex-wrap">
                    {!filters.compareMode && (
                        <LemonSegmentedButton<TracingViewMode>
                            size="small"
                            value={filters.viewMode}
                            onChange={setViewMode}
                            options={[
                                {
                                    value: 'traces',
                                    label: 'Traces',
                                    icon: <IconListTree />,
                                    tooltip: 'Group matching spans by trace — one row per trace (its root span)',
                                    'data-attr': 'tracing-view-mode-traces',
                                },
                                {
                                    value: 'spans',
                                    label: 'Spans',
                                    icon: <IconList />,
                                    tooltip: 'Show every matching span individually, including child spans',
                                    'data-attr': 'tracing-view-mode-spans',
                                },
                            ]}
                        />
                    )}
                    <LemonSwitch
                        label="Compare"
                        checked={filters.compareMode}
                        onChange={setCompareMode}
                        bordered
                        size="small"
                    />
                </div>
            )}
        </div>
    )
}
