import { type ReactElement, useEffect, useRef, useState } from 'react'

export type BarLayout = 'grouped' | 'stacked' | 'percent'

export interface ChartConfig {
    showTrendLine: boolean
    showMovingAverage: boolean
    showValueLabels: boolean
    /** Line chart only — render as a 100% stacked area. */
    percentStack: boolean
    /** Bar chart only. */
    barLayout: BarLayout
}

export const DEFAULT_CHART_CONFIG: ChartConfig = {
    showTrendLine: false,
    showMovingAverage: false,
    showValueLabels: false,
    percentStack: false,
    barLayout: 'grouped',
}

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
}

export function ChartSettings({ chartMode, config, onChange }: ChartSettingsProps): ReactElement {
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
                                    label="Trend line"
                                    checked={config.showTrendLine}
                                    onChange={(v) => update('showTrendLine', v)}
                                />
                                <Toggle
                                    label="Moving average"
                                    checked={config.showMovingAverage}
                                    onChange={(v) => update('showMovingAverage', v)}
                                />
                                <Toggle
                                    label="Value labels"
                                    checked={config.showValueLabels}
                                    onChange={(v) => update('showValueLabels', v)}
                                />
                                <Toggle
                                    label="Percent stack"
                                    checked={config.percentStack}
                                    onChange={(v) => update('percentStack', v)}
                                />
                            </>
                        ) : (
                            <>
                                <div>
                                    <div className="mb-1 text-text-secondary">Bar layout</div>
                                    <div className="flex gap-2">
                                        {(['grouped', 'stacked', 'percent'] as const).map((layout) => (
                                            <label key={layout} className="inline-flex items-center gap-1">
                                                <input
                                                    type="radio"
                                                    name="bar-layout"
                                                    checked={config.barLayout === layout}
                                                    onChange={() => update('barLayout', layout)}
                                                />
                                                {layout}
                                            </label>
                                        ))}
                                    </div>
                                </div>
                                <Toggle
                                    label="Value labels"
                                    checked={config.showValueLabels}
                                    onChange={(v) => update('showValueLabels', v)}
                                />
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
}: {
    label: string
    checked: boolean
    onChange: (next: boolean) => void
}): ReactElement {
    return (
        <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
            {label}
        </label>
    )
}
