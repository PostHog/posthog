import { ArrowLeft } from 'lucide-react'
import { type CSSProperties, type ReactElement, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { Button, Text } from '@posthog/quill'

import type { ExplainChartData, StoryChapter, StoryEvidence } from './explainChartTypes'
import { StoryChapterView } from './StoryChapterView'
import { StoryChartOverlay } from './StoryChartOverlay'
import { buildStoryPages, type StoryPage } from './storyPages'
import { StoryPanelResizeGrip } from './StoryPanelResizeGrip'
import { StorySingleChapterView } from './StorySingleChapterView'
import { StorySteps } from './StorySteps'
import { StorySummaryView } from './StorySummaryView'

// The panel takes a share of the space, so a small screen keeps more of it for the chart.
const DEFAULT_PANEL_WIDTH = 'clamp(280px, 35%, 420px)'
const MIN_PANEL_WIDTH = 240
const MIN_CHART_WIDTH = 320

const wholeFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const smallFormat = new Intl.NumberFormat('en-US', { maximumSignificantDigits: 2 })
const defaultFormat = (value: number): string =>
    (value !== 0 && Math.abs(value) < 1 ? smallFormat : wholeFormat).format(value)

export type StoryNavigationSource = 'marker' | 'step' | 'summary_list' | 'next' | 'back'

export interface StoryPageChange {
    index: number
    fromIndex: number
    source: StoryNavigationSource
}

export interface StoryEvidenceCharts {
    canShow: (item: StoryEvidence) => boolean
    prefetch: (items: StoryEvidence[]) => void
    /** Draws the chart, fading every series that the evidence's text does not name. */
    render: (item: StoryEvidence) => ReactNode
    onShow?: (item: StoryEvidence) => void
}

export interface ExplainChartViewProps {
    data: ExplainChartData
    /** Draws the chart with the overlay as a child, so the overlay can read the chart's scales. */
    renderChart: (overlay: ReactNode) => ReactNode
    openLink: (url: string) => void
    title?: string | null
    formatValue?: (value: number) => string
    onPageChange?: (change: StoryPageChange) => void
    evidenceCharts?: StoryEvidenceCharts
}

function hasChapter(page: StoryPage): page is StoryPage & { chapter: StoryChapter } {
    return page.chapter !== null
}

function warningMessages(warnings: unknown[] = []): string[] {
    return warnings.map((warning) =>
        typeof warning === 'string' ? warning : ((warning as { message?: string }).message ?? JSON.stringify(warning))
    )
}

function seriesNoteOf(data: ExplainChartData): string | null {
    if (data.results.length < 2) {
        return null
    }
    const series = data.results[data.seriesIndex]
    const label = series?.label || `series ${data.seriesIndex + 1}`
    return `This follows ${label}, one of the ${data.results.length} series on the chart.`
}

export function ExplainChartView({
    data,
    renderChart,
    openLink,
    title,
    formatValue = defaultFormat,
    onPageChange,
    evidenceCharts,
}: ExplainChartViewProps): ReactElement {
    const pages = useMemo(() => buildStoryPages(data, formatValue), [data, formatValue])
    // With one chapter, a summary page and steps add nothing, so the explanation is that chapter alone.
    const singleChapter = pages.length === 2
    const [activeIndex, setActiveIndex] = useState(singleChapter ? 1 : 0)
    const [previewIndex, setPreviewIndex] = useState<number | null>(null)
    const [shownEvidenceIndex, setShownEvidenceIndex] = useState<number | null>(null)
    // Null keeps the default width until the panel is dragged.
    const [panelWidth, setPanelWidth] = useState<number | null>(null)
    const rowRef = useRef<HTMLDivElement>(null)
    const asideRef = useRef<HTMLElement>(null)
    const maxPanelWidth = (): number =>
        Math.max(MIN_PANEL_WIDTH, (rowRef.current?.clientWidth ?? Infinity) - MIN_CHART_WIDTH)
    const active = pages[activeIndex] ?? pages[0]!
    const hasNext = activeIndex + 1 < pages.length
    const shownEvidence: StoryEvidence | null =
        shownEvidenceIndex === null ? null : (active.chapter?.evidence[shownEvidenceIndex] ?? null)
    const evidenceView = shownEvidence && evidenceCharts?.canShow(shownEvidence) ? shownEvidence : null

    const prefetch = evidenceCharts?.prefetch
    useEffect(() => {
        if (active.chapter?.evidence.length) {
            prefetch?.(active.chapter.evidence)
        }
    }, [active, prefetch])

    const canShowChart = (item: StoryEvidence): boolean => !!evidenceCharts?.canShow(item)

    const toggleEvidenceChart = (index: number): void => {
        const item = active.chapter?.evidence[index]
        if (index === shownEvidenceIndex || !item) {
            setShownEvidenceIndex(null)
            return
        }
        setShownEvidenceIndex(index)
        evidenceCharts?.onShow?.(item)
    }

    const select = (index: number, source: StoryNavigationSource): void => {
        setPreviewIndex(null)
        setShownEvidenceIndex(null)
        if (index === activeIndex) {
            return
        }
        setActiveIndex(index)
        onPageChange?.({ index, fromIndex: activeIndex, source })
    }

    const overlay = (
        <StoryChartOverlay
            seriesKey={String(data.seriesIndex)}
            pages={pages}
            highlightedIndex={previewIndex ?? activeIndex}
            activeIndex={activeIndex}
            showMarkers={!singleChapter}
            onSelect={(index) => select(index, 'marker')}
        />
    )

    return (
        <div className="@container/story" data-attr="explain-chart">
            <div ref={rowRef} className="flex flex-col @3xl/story:flex-row">
                <div className="min-w-0 flex-1">
                    {/* The header is one line in both views, so showing an evidence chart moves nothing. The evidence's text stays highlighted in the panel. */}
                    {evidenceCharts && evidenceView ? (
                        <>
                            <div className="box-content flex h-5 items-center pb-2">
                                <Button
                                    variant="outline"
                                    size="xs"
                                    onClick={() => setShownEvidenceIndex(null)}
                                    data-attr="explain-chart-evidence-back"
                                >
                                    <ArrowLeft className="size-3" />
                                    Back to the explanation
                                </Button>
                            </div>
                            {evidenceCharts.render(evidenceView)}
                        </>
                    ) : (
                        <>
                            {title && (
                                <Text size="sm" weight="medium" className="box-content block h-5 truncate pb-2">
                                    {title}
                                </Text>
                            )}
                            {renderChart(overlay)}
                        </>
                    )}
                </div>
                <aside
                    ref={asideRef}
                    className="relative shrink-0 border-t border-border @3xl/story:w-(--story-panel-width) @3xl/story:border-t-0 @3xl/story:border-l"
                    style={
                        {
                            // The browser keeps room for the chart when the space shrinks after a drag.
                            '--story-panel-width':
                                panelWidth === null
                                    ? DEFAULT_PANEL_WIDTH
                                    : `clamp(${MIN_PANEL_WIDTH}px, ${panelWidth}px, calc(100% - ${MIN_CHART_WIDTH}px))`,
                        } as CSSProperties
                    }
                    aria-label="Explanation of this chart"
                >
                    <StoryPanelResizeGrip
                        getWidth={() => asideRef.current?.offsetWidth ?? panelWidth ?? MIN_PANEL_WIDTH}
                        minWidth={MIN_PANEL_WIDTH}
                        maxWidth={maxPanelWidth()}
                        onResize={(width) => setPanelWidth(Math.min(Math.max(width, MIN_PANEL_WIDTH), maxPanelWidth()))}
                        onReset={() => setPanelWidth(null)}
                    />
                    {/* Beside the chart, the panel takes the chart's height and the page scrolls inside it. */}
                    <div className="flex flex-col @3xl/story:absolute @3xl/story:inset-0">
                        {/* Keyed on the page, so each chapter opens at its top and an evidence chart keeps the scroll. */}
                        <div key={activeIndex} className="min-h-0 flex-1 p-4 @3xl/story:overflow-y-auto">
                            {singleChapter && hasChapter(active) ? (
                                <StorySingleChapterView
                                    headline={data.headline}
                                    seriesNote={seriesNoteOf(data)}
                                    warnings={warningMessages(data.warnings)}
                                    page={active}
                                    openLink={openLink}
                                    canShowChart={canShowChart}
                                    shownEvidenceIndex={shownEvidenceIndex}
                                    onToggleChart={toggleEvidenceChart}
                                />
                            ) : hasChapter(active) ? (
                                <StoryChapterView
                                    page={active}
                                    openLink={openLink}
                                    canShowChart={canShowChart}
                                    shownEvidenceIndex={shownEvidenceIndex}
                                    onToggleChart={toggleEvidenceChart}
                                />
                            ) : (
                                <StorySummaryView
                                    headline={data.headline}
                                    pages={pages}
                                    seriesNote={seriesNoteOf(data)}
                                    warnings={warningMessages(data.warnings)}
                                    onSelect={(index) => select(index, 'summary_list')}
                                    onPreview={setPreviewIndex}
                                />
                            )}
                        </div>
                        {/* One chapter shows on its own and a chart with none shows its summary alone, so steps add nothing. */}
                        {pages.length > 2 && (
                            <div className="flex items-center justify-between gap-3 border-t border-border py-2 ps-4 pe-3">
                                <StorySteps
                                    pages={pages}
                                    activeIndex={activeIndex}
                                    onSelect={(index) => select(index, 'step')}
                                    onPreview={setPreviewIndex}
                                />
                                <div className="flex shrink-0 gap-1">
                                    {activeIndex > 0 && (
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            onClick={() => select(activeIndex - 1, 'back')}
                                            data-attr="explain-chart-back"
                                        >
                                            Back
                                        </Button>
                                    )}
                                    {hasNext && (
                                        <Button
                                            variant="primary"
                                            size="sm"
                                            onClick={() => select(activeIndex + 1, 'next')}
                                            data-attr="explain-chart-next"
                                        >
                                            Next
                                        </Button>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </aside>
            </div>
        </div>
    )
}
