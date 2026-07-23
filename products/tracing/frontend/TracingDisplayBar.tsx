import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight, IconList, IconListTree, IconStack } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, type LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { CompareMenuButton } from './components/Comparison/CompareMenuButton'
import { tracingConfigLogic } from './tracingConfigLogic'
import { tracingSceneLogic, type TracingDisplayMode } from './tracingSceneLogic'

/**
 * The bar above the results, mirroring logs' LogsDisplayBar:
 *
 *  - left: the facet rail toggle, the row-mode selector (Traces ⇄ Spans ⇄ Operations — what
 *    each result row represents), and the matching-count indicator.
 *  - right: Compare, hidden on the Operations view where it doesn't apply.
 */
export function TracingDisplayBar(): JSX.Element {
    const { totalMatchingFilters, compareActive, displayMode, operationsViewEnabled } = useValues(tracingSceneLogic())
    const { setDisplayMode } = useActions(tracingSceneLogic())
    const { featureFlags } = useValues(featureFlagLogic)
    const { facetRailCollapsed } = useValues(tracingConfigLogic)
    const { setFacetRailCollapsed } = useActions(tracingConfigLogic)

    const facetRailEnabled = !!featureFlags[FEATURE_FLAGS.TRACING_FACET_RAIL]
    const inTracesView = displayMode !== 'operations'
    const showCount = inTracesView && !compareActive && totalMatchingFilters > 0

    // data-attrs keep the names from the two controls this one replaced, for analytics continuity.
    const displayModeOptions: LemonSegmentedButtonOption<TracingDisplayMode>[] = [
        {
            value: 'traces',
            label: 'Traces',
            icon: <IconListTree />,
            tooltip: 'Group matching spans by trace, one row per trace (its root span)',
            'data-attr': 'tracing-view-mode-traces',
        },
        {
            value: 'spans',
            label: 'Spans',
            icon: <IconList />,
            tooltip: 'Show every matching span individually, including child spans',
            // The comparison table aggregates by operation, so span granularity has no effect there.
            disabledReason: compareActive ? 'Not available while comparing' : undefined,
            'data-attr': 'tracing-view-mode-spans',
        },
        ...(operationsViewEnabled
            ? [
                  {
                      value: 'operations' as const,
                      label: 'Operations',
                      icon: <IconStack />,
                      tooltip: 'Aggregate matching spans by operation (service and span name)',
                      'data-attr': 'tracing-display-tab-operations',
                  },
              ]
            : []),
    ]

    return (
        <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
                {facetRailEnabled && (
                    <LemonButton
                        size="small"
                        icon={facetRailCollapsed ? <IconChevronRight /> : <IconChevronLeft />}
                        onClick={() => setFacetRailCollapsed(!facetRailCollapsed)}
                        aria-label={facetRailCollapsed ? 'Show filters' : 'Hide filters'}
                        data-attr="tracing-facet-rail-toggle"
                    >
                        {facetRailCollapsed ? 'Show filters' : 'Hide filters'}
                    </LemonButton>
                )}
                <LemonSegmentedButton<TracingDisplayMode>
                    size="small"
                    value={displayMode}
                    onChange={setDisplayMode}
                    options={displayModeOptions}
                />
                {/* No loading guard: keep the last (view-mode-independent) count visible across reloads,
                    so a Traces/Spans switch doesn't flicker the label out and back in. */}
                {showCount && (
                    <span className="text-muted text-xs">
                        {humanFriendlyNumber(totalMatchingFilters)} {displayMode === 'spans' ? 'spans' : 'traces'}{' '}
                        matching filters
                    </span>
                )}
            </div>
            {inTracesView && (
                <div className="flex items-center gap-1.5 flex-wrap">
                    <CompareMenuButton />
                </div>
            )}
        </div>
    )
}
