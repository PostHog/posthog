import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/quill'

import {
    DEFAULT_CUSTOM_COMPARISON,
    TIME_COMPARE_PRESET_DEFS,
    TIME_COMPARE_PRESETS,
    type TimeComparePreset,
    tracingFiltersLogic,
} from '../../tracingFiltersLogic'

/**
 * Entry point for comparisons: a menu of baseline presets instead of a bare on/off toggle,
 * so the user picks *what* to compare against. The active comparison is described by the
 * ComparisonBar rendered above the results.
 */
export function CompareMenuButton(): JSX.Element {
    const { comparison, compareActive, sparklineWindowMs } = useValues(tracingFiltersLogic)
    const { setComparison } = useActions(tracingFiltersLogic)

    const activePreset = comparison?.mode === 'time' ? comparison.preset : null
    const rangeDurationMs = sparklineWindowMs.endMs - sparklineWindowMs.startMs

    // A preset whose shift is shorter than the selected range would produce a baseline that
    // mostly overlaps the current window — deltas near zero that read as "nothing changed".
    const presetDisabled = (preset: TimeComparePreset): boolean => {
        const shiftMs = TIME_COMPARE_PRESET_DEFS[preset].shiftMs
        return shiftMs !== null && shiftMs < rangeDurationMs
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <LemonButton
                        size="small"
                        type="secondary"
                        active={compareActive}
                        data-attr="tracing-compare-menu"
                    />
                }
            >
                Compare
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[220px]">
                <DropdownMenuRadioGroup
                    value={activePreset ?? ''}
                    onValueChange={(preset: string) => {
                        // Re-selecting the active preset would refetch identical data and wipe
                        // any dragged custom windows.
                        if (preset !== activePreset) {
                            setComparison({ ...DEFAULT_CUSTOM_COMPARISON, preset: preset as TimeComparePreset })
                        }
                    }}
                >
                    <DropdownMenuLabel>Compare this time range</DropdownMenuLabel>
                    {TIME_COMPARE_PRESETS.map((preset) => {
                        const disabled = presetDisabled(preset)
                        return (
                            <DropdownMenuRadioItem
                                key={preset}
                                value={preset}
                                disabled={disabled}
                                data-attr={`tracing-compare-${preset.replace(/_/g, '-')}`}
                            >
                                {TIME_COMPARE_PRESET_DEFS[preset].label}
                                {disabled && <span className="text-muted ml-1">(range too wide)</span>}
                            </DropdownMenuRadioItem>
                        )
                    })}
                </DropdownMenuRadioGroup>
                {compareActive && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => setComparison(null)} data-attr="tracing-compare-exit">
                            Exit comparison
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
