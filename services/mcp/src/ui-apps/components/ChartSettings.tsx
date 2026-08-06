import { type ReactElement, useEffect, useId, useRef, useState } from 'react'

import { Button, Label, Switch } from '@posthog/quill'

import { type ChartConfig, Y_UNIT_OPTIONS, type YUnit } from './chartSettingsConfig'

interface ChartSettingsProps {
    family: 'line' | 'bar'
    config: ChartConfig
    onChange: (config: ChartConfig) => void
    /** Disabled in area mode, where overlays would draw against the stacked totals. */
    derivedSeriesDisabled?: boolean
    /** Disabled for non-stacked types — only area / stacked bar have a 100% view. */
    percentStackDisabled?: boolean
}

export function ChartSettings({
    family,
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
                        {family === 'line' && (
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
                            {/* eslint-disable-next-line react/forbid-elements */}
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
