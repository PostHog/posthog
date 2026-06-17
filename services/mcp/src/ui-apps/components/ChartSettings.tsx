import { type ReactElement, useEffect, useId, useRef, useState } from 'react'

import { Button, Label, Switch } from '@posthog/quill'

import { type ChartConfig, Y_UNIT_OPTIONS, type YUnit } from './chartSettingsConfig'

// Hand-rolled popover (no Radix/Floating UI portals) for the same reason as `charts/Select.tsx`:
// the app runs in a sandboxed iframe where portalled content can land in a different stacking
// context. The click-away listener binds to the iframe's own document, so it stays self-contained.

interface ChartSettingsProps {
    chartMode: 'line' | 'bar'
    config: ChartConfig
    onChange: (config: ChartConfig) => void
    /** When true, derived-series toggles (trend line / moving average / CI) are disabled —
     *  area mode auto-stacks, and overlays drawn at raw per-series values look broken
     *  against the stacked totals. Mirrors the web trends Options behaviour. */
    derivedSeriesDisabled?: boolean
    /** When true, the percent stack toggle is disabled — only stacked renderings (area,
     *  stacked bar) support a 100% view. */
    percentStackDisabled?: boolean
}

export function ChartSettings({
    chartMode,
    config,
    onChange,
    derivedSeriesDisabled = false,
    percentStackDisabled = false,
}: ChartSettingsProps): ReactElement {
    const [open, setOpen] = useState(false)
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!open) {
            return
        }
        const onDocumentClick = (e: MouseEvent): void => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setOpen(false)
            }
        }
        document.addEventListener('mousedown', onDocumentClick)
        return () => document.removeEventListener('mousedown', onDocumentClick)
    }, [open])

    const update = <K extends keyof ChartConfig>(key: K, value: ChartConfig[K]): void => {
        onChange({ ...config, [key]: value })
    }

    return (
        <div ref={containerRef} className="relative">
            <Button
                variant="outline"
                size="sm"
                onClick={() => setOpen((o) => !o)}
                aria-label="Chart options"
                aria-expanded={open}
            >
                Options
            </Button>
            {open && (
                <div
                    role="dialog"
                    className="absolute right-0 top-full z-10 mt-1 w-56 rounded-sm border border-input bg-background p-3 shadow-lg"
                >
                    <div className="flex flex-col gap-2 text-xs">
                        <Toggle
                            label="Value labels"
                            checked={config.showValueLabels}
                            onChange={(v) => update('showValueLabels', v)}
                        />
                        {chartMode === 'line' && (
                            <>
                                <Toggle
                                    label="Trend line"
                                    checked={config.showTrendLine}
                                    disabled={derivedSeriesDisabled}
                                    onChange={(v) => update('showTrendLine', v)}
                                />
                                <Toggle
                                    label="Confidence intervals"
                                    checked={config.showConfidenceIntervals}
                                    disabled={derivedSeriesDisabled}
                                    onChange={(v) => update('showConfidenceIntervals', v)}
                                />
                            </>
                        )}
                        <Toggle
                            label="Percent stack"
                            checked={config.percentStack}
                            disabled={percentStackDisabled}
                            onChange={(v) => update('percentStack', v)}
                        />
                        <div className="mt-1">
                            <div className="mb-1 text-muted-foreground">Y-axis unit</div>
                            <select
                                value={config.yUnit}
                                onChange={(e) => update('yUnit', e.target.value as YUnit)}
                                className="w-full cursor-pointer rounded-sm border border-input bg-background px-2 py-1 text-xs text-foreground"
                            >
                                {Y_UNIT_OPTIONS.map((opt) => (
                                    <option key={opt.value} value={opt.value}>
                                        {opt.label}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

function Toggle({
    label,
    checked,
    onChange,
    disabled = false,
}: {
    label: string
    checked: boolean
    onChange: (next: boolean) => void
    disabled?: boolean
}): ReactElement {
    const id = useId()
    return (
        <div className={`flex items-center justify-between gap-2 ${disabled ? 'opacity-50' : ''}`}>
            <Label htmlFor={id} className={disabled ? 'cursor-not-allowed' : 'cursor-pointer'}>
                {label}
            </Label>
            <Switch
                id={id}
                size="sm"
                checked={checked && !disabled}
                disabled={disabled}
                onCheckedChange={(next) => onChange(next)}
            />
        </div>
    )
}
