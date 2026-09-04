import './ReplayVisionObservationPreview.scss'

import { sparkPaths } from 'lib/components/ProductEmptyState/previewSparkline'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { ScannerTypeBadge } from '../components/ScannerTypeBadge'
import { ScannerType } from '../replay_scanners/types'

interface PreviewObservation {
    scannerType: ScannerType
    scannerName: string
    tag: { label: string; type: 'warning' | 'danger' } | null
    text: string
}

// Invented results covering the four scanner types, so the examples match what the
// create flow offers next. Static by design: an illustration, not data.
const OBSERVATIONS: PreviewObservation[] = [
    {
        scannerType: 'monitor',
        scannerName: 'Dead-end pages',
        tag: { label: 'yes', type: 'warning' },
        text: 'Landed on the integrations page from a search result, scrolled to the bottom, and left without clicking anything.',
    },
    {
        scannerType: 'scorer',
        scannerName: 'Frustration score',
        tag: { label: '7/10', type: 'warning' },
        text: 'Clicked a disabled save button four times, reloaded the page, and re-entered the form before finishing signup.',
    },
    {
        scannerType: 'classifier',
        scannerName: 'Session outcome',
        tag: { label: 'blocked_by_error', type: 'danger' },
        text: 'Checkout failed twice with a card validation error. The user retried once, then left from the payment step.',
    },
    {
        scannerType: 'summarizer',
        scannerName: 'Session summary',
        tag: null,
        text: 'Compared the two paid plans, read the SSO docs, invited a teammate, and started a trial from the billing page.',
    },
]

const FILTERS: { id: string; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'monitor', label: 'Monitor' },
    { id: 'scorer', label: 'Scorer' },
    { id: 'classifier', label: 'Classifier' },
    { id: 'summarizer', label: 'Summarizer' },
]

// A hand-authored series for the sparkline: abstract, just enough to read as a rising trend.
const SPARK = [3, 5, 4, 6, 7, 6, 9, 8, 11, 10, 13, 14]
const { line, area } = sparkPaths(SPARK)

/**
 * Example-data preview for the Replay vision empty state. All interaction and motion
 * are pure CSS (hidden radios drive the type filter) - no timers or state, per the
 * preview rules in the `building-product-empty-states` skill.
 */
export function ReplayVisionObservationPreview(_: { mode: ProductEmptyStateMode }): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className="flex flex-col gap-3">
            <div className="VisionPreview">
                {/* Filter state, before the chips/rows so `:checked ~` can style them. */}
                {FILTERS.map((filter) => (
                    <input
                        key={filter.id}
                        type="radio"
                        name="vision-preview-filter"
                        id={`vision-preview-${filter.id}`}
                        defaultChecked={filter.id === 'all'}
                        className="VisionPreview__radio"
                    />
                ))}

                <div className="VisionPreview__head">
                    <span className="VisionPreview__title">Observations</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="VisionPreview__chips">
                    {FILTERS.map((filter) => (
                        <label
                            key={filter.id}
                            htmlFor={`vision-preview-${filter.id}`}
                            className={`VisionPreview__chip VisionPreview__chip--${filter.id}`}
                        >
                            {filter.label}
                        </label>
                    ))}
                </div>

                <div className="VisionPreview__rows">
                    {OBSERVATIONS.map((observation) => (
                        <div
                            key={observation.scannerName}
                            className="VisionPreview__row"
                            data-t={observation.scannerType}
                        >
                            <div className="flex items-center gap-2">
                                <ScannerTypeBadge scannerType={observation.scannerType} size="small" />
                                <span className="VisionPreview__scanner">{observation.scannerName}</span>
                                {observation.tag && (
                                    <LemonTag type={observation.tag.type} size="small" className="ml-auto">
                                        {observation.tag.label}
                                    </LemonTag>
                                )}
                            </div>
                            <p className="VisionPreview__text">{observation.text}</p>
                        </div>
                    ))}
                </div>
            </div>

            <div className={cn('VisionSpark', isStatic && 'VisionSpark--static')}>
                <div className="VisionSpark__head">
                    <span className="VisionSpark__title">Sessions scanned · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="VisionSpark__value">
                    412
                    <span className="VisionSpark__delta">▲ 23%</span>
                </div>

                <div className="VisionSpark__chart">
                    <svg
                        className="VisionSpark__svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="VisionSpark__area" d={area} />
                        <path className="VisionSpark__line" d={line} vectorEffect="non-scaling-stroke" />
                        <path
                            className="VisionSpark__trace"
                            d={line}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>
                </div>

                <div className="VisionSpark__caption">Every result is an event you can query, graph, and alert on</div>
            </div>
        </div>
    )
}
