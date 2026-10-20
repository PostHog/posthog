import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { DashboardTile } from '~/types'

import { MAX_INSIGHTS, insightSelectorLogic } from './insightSelectorLogic'

interface InsightSelectorProps {
    tiles: DashboardTile[]
    selectedInsightIds: number[]
    onChange: (ids: number[]) => void
    onDefaultsApplied?: (selectedIds: number[]) => void
}

export function InsightSelector({
    tiles,
    selectedInsightIds,
    onChange,
    onDefaultsApplied,
}: InsightSelectorProps): JSX.Element {
    const logic = insightSelectorLogic({ tiles, selectedInsightIds })
    const {
        filteredTiles,
        insightTiles,
        showSearch,
        searchTerm,
        userHasInteracted,
        validSelectedIds,
        unavailableSelectedIds,
    } = useValues(logic)
    const { setSearchTerm, setUserHasInteracted } = useActions(logic)

    useEffect(() => {
        // Auto-select the first N insights for new subscriptions (when nothing is selected yet)
        if (insightTiles.length > 0 && selectedInsightIds.length === 0 && !userHasInteracted) {
            const defaultSelection = insightTiles.slice(0, MAX_INSIGHTS).map((tile) => tile.insight!.id)
            onChange(defaultSelection)
            onDefaultsApplied?.(defaultSelection)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [insightTiles, selectedInsightIds, userHasInteracted])

    const selectedCount = validSelectedIds.length
    const selectableCount = Math.min(insightTiles.length, MAX_INSIGHTS)
    const atMaxLimit = selectedCount >= MAX_INSIGHTS

    const toggleInsight = (insightId: number): void => {
        setUserHasInteracted()
        if (validSelectedIds.includes(insightId)) {
            const newIds = selectedInsightIds.filter((id) => id !== insightId)
            onChange(newIds)
        } else if (!atMaxLimit) {
            onChange([...selectedInsightIds, insightId])
        }
    }

    return (
        <div className="border rounded p-2 space-y-2">
            {unavailableSelectedIds.length > 0 && (
                <LemonBanner type="warning">
                    <div className="space-y-2">
                        <strong>Selected insights are unavailable on this dashboard.</strong>
                        <p>
                            <span>Unavailable insights: </span>
                            <span>{unavailableSelectedIds.length}</span>
                        </p>
                        {validSelectedIds.length === 0 && (
                            <p>This subscription cannot send because none of its selected insights are available.</p>
                        )}
                        <p>
                            Remove the unavailable insights and select replacements if needed. Save to apply your
                            changes.
                        </p>
                        <ul className="space-y-1">
                            {unavailableSelectedIds.map((id) => (
                                <li key={id} className="flex flex-wrap items-center justify-between gap-2">
                                    <span>Unavailable insight (ID: {id})</span>
                                    <LemonButton
                                        size="small"
                                        data-attr="subscription-remove-unavailable-insight"
                                        aria-label={`Remove insight ${id} from subscription`}
                                        onClick={() => {
                                            setUserHasInteracted()
                                            onChange(selectedInsightIds.filter((selectedId) => selectedId !== id))
                                        }}
                                    >
                                        Remove from subscription
                                    </LemonButton>
                                </li>
                            ))}
                        </ul>
                        {unavailableSelectedIds.length > 1 && (
                            <LemonButton
                                size="small"
                                data-attr="subscription-remove-all-unavailable-insights"
                                onClick={() => {
                                    setUserHasInteracted()
                                    onChange(validSelectedIds)
                                }}
                            >
                                Remove all unavailable
                            </LemonButton>
                        )}
                    </div>
                </LemonBanner>
            )}
            {insightTiles.length === 0 && (
                <p className="text-secondary text-sm">
                    No insights found in this dashboard. Add an insight before saving.
                </p>
            )}
            <div className="flex flex-wrap justify-between items-center gap-2 text-sm">
                <span className="font-medium">
                    {selectedCount} of {selectableCount} insights selected
                </span>
                {selectedCount === 0 && <span className="text-danger">Select at least one insight</span>}
            </div>
            {showSearch && (
                <LemonInput
                    type="search"
                    placeholder="Search insights..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    fullWidth
                />
            )}
            <div className="border-t pt-2 space-y-1 max-h-[200px] overflow-y-auto">
                {filteredTiles.length === 0 && insightTiles.length > 0 ? (
                    <div className="text-secondary text-sm py-2">No insights match your search.</div>
                ) : (
                    filteredTiles.map((tile) => {
                        const insight = tile.insight!
                        const isChecked = validSelectedIds.includes(insight.id)
                        const isDisabled = !isChecked && atMaxLimit
                        return (
                            <LemonCheckbox
                                key={tile.id}
                                checked={isChecked}
                                onChange={() => toggleInsight(insight.id)}
                                label={insight.name || insight.derived_name || 'Untitled insight'}
                                disabledReason={
                                    isDisabled && 'Maximum number of insights selected. Deselect one to add another.'
                                }
                            />
                        )
                    })
                )}
            </div>
            {atMaxLimit && (
                <div className="text-xs text-secondary">
                    Maximum {MAX_INSIGHTS} insights. Deselect one to add another.
                </div>
            )}
        </div>
    )
}
