import { type ReactElement, useEffect, useRef, useState } from 'react'

import type { YAxisFormat } from 'lib/hog-charts/utils/y-formatters'

export type YUnit = YAxisFormat

export interface ChartConfig {
    showTrendLine: boolean
    showMovingAverage: boolean
    showValueLabels: boolean
    /** Line / area only. */
    showConfidenceIntervals: boolean
    /** Line / area only — render as a 100% stacked view. */
    percentStack: boolean
    yUnit: YUnit
}

export const DEFAULT_CHART_CONFIG: ChartConfig = {
    showTrendLine: false,
    showMovingAverage: false,
    showValueLabels: false,
    showConfidenceIntervals: false,
    percentStack: false,
    yUnit: 'numeric',
}

const Y_UNIT_OPTIONS: { value: YUnit; label: string }[] = [
    { value: 'numeric', label: 'Numeric' },
    { value: 'short', label: 'Compact (1.2K)' },
    { value: 'percentage', label: 'Percentage (0–100)' },
    { value: 'percentage_scaled', label: 'Percentage (0–1)' },
    { value: 'duration', label: 'Duration (s)' },
    { value: 'duration_ms', label: 'Duration (ms)' },
    { value: 'currency', label: 'Currency' },
]

const STORAGE_KEY = 'mcp-trends-chart-config'

export function loadChartConfig(): ChartConfig {
    try {
        const raw = window.localStorage.getItem(STORAGE_KEY)
        if (!raw) {
            return DEFAULT_CHART_CONFIG
        }
        const parsed = JSON.parse(raw) as Partial<ChartConfig>
        return { ...DEFAULT_CHART_CONFIG, ...parsed }
    } catch {
        // Sandboxed iframes may refuse localStorage access — fall back to defaults.
        return DEFAULT_CHART_CONFIG
    }
}

export function saveChartConfig(config: ChartConfig): void {
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
    } catch {
        // Best-effort persistence; swallow when storage is unavailable.
    }
}

interface ChartSettingsProps {
    chartMode: 'line' | 'bar'
    config: ChartConfig
    onChange: (config: ChartConfig) => void
    /** When true, derived-series toggles (trend line / moving average / CI) are disabled —
     *  area mode auto-stacks, and overlays drawn at raw per-series values look broken
     *  against the stacked totals. Mirrors the web trends Options behaviour. */
    derivedSeriesDisabled?: boolean
}

export function ChartSettings({
    chartMode,
    config,
    onChange,
    derivedSeriesDisabled = false,
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
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                aria-label="Chart options"
                aria-expanded={open}
                className="inline-flex items-center justify-center rounded-md border border-border-primary bg-bg-primary px-2 py-1 text-xs hover:bg-bg-hover"
            >
                Options
            </button>
            {open && (
                <div
                    role="dialog"
                    className="absolute right-0 top-full z-10 mt-1 w-56 rounded-md border border-border-primary bg-bg-primary p-3 shadow-lg"
                >
                    <div className="flex flex-col gap-2 text-xs">
                        {chartMode === 'line' ? (
                            <>
                                <Toggle
                                    label="Value labels"
                                    checked={config.showValueLabels}
                                    onChange={(v) => update('showValueLabels', v)}
                                />
                                <Toggle
                                    label="Trend line"
                                    checked={config.showTrendLine}
                                    disabled={derivedSeriesDisabled}
                                    onChange={(v) => update('showTrendLine', v)}
                                />
                                <Toggle
                                    label="Moving average"
                                    checked={config.showMovingAverage}
                                    disabled={derivedSeriesDisabled}
                                    onChange={(v) => update('showMovingAverage', v)}
                                />
                                <Toggle
                                    label="Confidence intervals"
                                    checked={config.showConfidenceIntervals}
                                    disabled={derivedSeriesDisabled}
                                    onChange={(v) => update('showConfidenceIntervals', v)}
                                />
                                <Toggle
                                    label="Percent stack"
                                    checked={config.percentStack}
                                    onChange={(v) => update('percentStack', v)}
                                />
                                <div className="mt-1">
                                    <div className="mb-1 text-text-secondary">Y-axis unit</div>
                                    <select
                                        value={config.yUnit}
                                        onChange={(e) => update('yUnit', e.target.value as YUnit)}
                                        className="w-full rounded-md border border-border-primary bg-bg-primary px-2 py-1 text-xs"
                                    >
                                        {Y_UNIT_OPTIONS.map((opt) => (
                                            <option key={opt.value} value={opt.value}>
                                                {opt.label}
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            </>
                        ) : (
                            <>
                                <Toggle
                                    label="Value labels"
                                    checked={config.showValueLabels}
                                    onChange={(v) => update('showValueLabels', v)}
                                />
                                <div className="mt-1">
                                    <div className="mb-1 text-text-secondary">Y-axis unit</div>
                                    <select
                                        value={config.yUnit}
                                        onChange={(e) => update('yUnit', e.target.value as YUnit)}
                                        className="w-full rounded-md border border-border-primary bg-bg-primary px-2 py-1 text-xs"
                                    >
                                        {Y_UNIT_OPTIONS.map((opt) => (
                                            <option key={opt.value} value={opt.value}>
                                                {opt.label}
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            </>
                        )}
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
    return (
        <label className={`inline-flex items-center gap-2 ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}>
            <input
                type="checkbox"
                checked={checked && !disabled}
                disabled={disabled}
                onChange={(e) => onChange(e.target.checked)}
            />
            {label}
        </label>
    )
}
