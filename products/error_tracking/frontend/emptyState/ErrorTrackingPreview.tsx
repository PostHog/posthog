import './ErrorTrackingPreview.scss'

import { Spinner } from '@posthog/lemon-ui'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored sparkline for the exceptions stat. The "after" series ticks up at the
// far right, where the newly-thrown exception lands.
const LINE_BEFORE = 'M 0 26 L 12 28 L 24 22 L 36 27 L 48 20 L 60 25 L 72 18 L 84 23 L 100 21'
const LINE_AFTER = 'M 0 26 L 12 28 L 24 22 L 36 27 L 48 20 L 60 25 L 72 18 L 84 23 L 92 21 L 100 9'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the error tracking empty state: an issue list, the mini app
 * that feeds it, and the stack trace of its top issue. Clicking "Place order" in the app
 * throws a bug on purpose - the app shows the crash, the issue's occurrence count ticks
 * up, the stack trace fills in, and the exceptions sparkline steps up. One hidden
 * checkbox drives it all via `:checked ~` styles - no timers or state, per the preview
 * rules in the `building-product-empty-states` skill. Before/after pairs are stacked in
 * `__swap` grids and crossfaded, so nothing shifts.
 */
export function ErrorTrackingPreview({ mode }: { mode: ProductEmptyStateMode }): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('ErrorPreview', isStatic && 'ErrorPreview--static')}>
            {/* Crash state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="error-preview-crash" className="ErrorPreview__checkbox" />

            <div className="ErrorPreview__app">
                <div className="ErrorPreview__chrome">
                    <span className="ErrorPreview__chrome-dot" />
                    <span className="ErrorPreview__chrome-dot" />
                    <span className="ErrorPreview__chrome-dot" />
                    <span className="ErrorPreview__url">yourapp.com/checkout</span>
                </div>
                <div className="ErrorPreview__screen">
                    <div className="ErrorPreview__order">
                        <span className="ErrorPreview__order-name">Sticker pack × 2</span>
                        <span className="ErrorPreview__order-price">$12.00</span>
                    </div>
                    <div className="ErrorPreview__toast-slot ErrorPreview__swap" aria-hidden="true">
                        <span className="ErrorPreview__toast-spacer ErrorPreview__when-before" />
                        <span className="ErrorPreview__toast ErrorPreview__when-after">
                            Uncaught TypeError: cart is undefined
                        </span>
                    </div>
                    <label htmlFor="error-preview-crash" className="ErrorPreview__cta">
                        <span className="ErrorPreview__swap">
                            <span className="ErrorPreview__when-before">Place order</span>
                            <span className="ErrorPreview__when-after">Place order (it throws)</span>
                        </span>
                    </label>
                    <div className="ErrorPreview__hint ErrorPreview__swap">
                        <span className="ErrorPreview__when-before">Click the button to throw a bug on purpose.</span>
                        <span className="ErrorPreview__when-after">
                            Caught, grouped, and counted below. Click again to undo.
                        </span>
                    </div>
                </div>
            </div>

            <div className="ErrorPreview__panel">
                <div className="ErrorPreview__head">
                    <span className="ErrorPreview__title">Issues</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                {mode === 'waiting-for-data' ? (
                    <div className="ErrorPreview__listening">
                        <Spinner className="text-sm" />
                        Listening for your first exception…
                    </div>
                ) : null}

                <div className="ErrorPreview__rows">
                    <div className="ErrorPreview__row ErrorPreview__row--hero">
                        <span className="ErrorPreview__dot" aria-hidden="true" />
                        <span className="ErrorPreview__issue">TypeError: cart is undefined</span>
                        <span className="ErrorPreview__fresh ErrorPreview__when-after">just now</span>
                        <span className="ErrorPreview__count ErrorPreview__swap">
                            <span className="ErrorPreview__when-before">12</span>
                            <span className="ErrorPreview__count--bumped ErrorPreview__when-after">13</span>
                        </span>
                    </div>
                    <div className="ErrorPreview__row">
                        <span className="ErrorPreview__dot" aria-hidden="true" />
                        <span className="ErrorPreview__issue">ReferenceError: gtag is not defined</span>
                        <span className="ErrorPreview__count">48</span>
                    </div>
                    <div className="ErrorPreview__row">
                        <span className="ErrorPreview__dot ErrorPreview__dot--resolved" aria-hidden="true" />
                        <span className="ErrorPreview__issue ErrorPreview__issue--resolved">
                            Failed to fetch: /api/products
                        </span>
                        <span className="ErrorPreview__count">7</span>
                    </div>
                </div>

                <div className="ErrorPreview__spark">
                    <div className="ErrorPreview__spark-head">
                        <span className="ErrorPreview__spark-title">Exceptions · 24 h</span>
                    </div>
                    <div className="ErrorPreview__spark-value">
                        <span className="ErrorPreview__swap">
                            <span className="ErrorPreview__when-before">214</span>
                            <span className="ErrorPreview__when-after">215</span>
                        </span>
                    </div>
                    <svg
                        className="ErrorPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <g className="ErrorPreview__spark-g ErrorPreview__when-before">
                            <path className="ErrorPreview__spark-area" d={areaPath(LINE_BEFORE)} />
                            <path
                                className="ErrorPreview__spark-line"
                                d={LINE_BEFORE}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="ErrorPreview__spark-trace"
                                d={LINE_BEFORE}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                        <g className="ErrorPreview__spark-g ErrorPreview__when-after">
                            <path className="ErrorPreview__spark-area" d={areaPath(LINE_AFTER)} />
                            <path
                                className="ErrorPreview__spark-line"
                                d={LINE_AFTER}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="ErrorPreview__spark-trace"
                                d={LINE_AFTER}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                    </svg>
                </div>
            </div>

            <div className="ErrorPreview__trace">
                <div className="ErrorPreview__head">
                    <span className="ErrorPreview__title">Stack trace</span>
                    <span className="ErrorPreview__fresh ErrorPreview__when-after">captured just now</span>
                </div>
                <div className="ErrorPreview__frames ErrorPreview__swap">
                    <div className="ErrorPreview__skeleton ErrorPreview__when-before" aria-hidden="true">
                        <span className="ErrorPreview__skeleton-line" />
                        <span className="ErrorPreview__skeleton-line" />
                        <span className="ErrorPreview__skeleton-line" />
                    </div>
                    <div className="ErrorPreview__frame-list ErrorPreview__when-after">
                        <div className="ErrorPreview__frame ErrorPreview__frame--app">
                            <span className="ErrorPreview__fn">processOrder</span>
                            <span className="ErrorPreview__loc">checkout/orders.ts:118</span>
                            <span className="ErrorPreview__frame-tag">in app</span>
                        </div>
                        <div className="ErrorPreview__frame">
                            <span className="ErrorPreview__fn">submitCart</span>
                            <span className="ErrorPreview__loc">checkout/CartButton.tsx:42</span>
                        </div>
                        <div className="ErrorPreview__frame">
                            <span className="ErrorPreview__fn">onClick</span>
                            <span className="ErrorPreview__loc">react-dom.production.min.js:189</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
