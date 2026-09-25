import './TracingPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

interface SpanRow {
    service: string
    name: string
    depth: number
    /** Offset and width, in % of the trace's duration. */
    offset: number
    width: number
    duration: string
    hero?: boolean
}

const SPAN_ROWS: SpanRow[] = [
    { service: 'web', name: 'POST /api/checkout', depth: 0, offset: 0, width: 100, duration: '812 ms' },
    { service: 'checkout-api', name: 'process_order', depth: 1, offset: 4, width: 92, duration: '748 ms' },
    { service: 'checkout-api', name: 'SELECT cart_items', depth: 2, offset: 6, width: 8, duration: '61 ms' },
    {
        service: 'payment-provider',
        name: 'POST /v1/charges',
        depth: 2,
        offset: 16,
        width: 79,
        duration: '640 ms',
        hero: true,
    },
    { service: 'checkout-api', name: 'INSERT orders', depth: 2, offset: 96, width: 3, duration: '24 ms' },
]

/**
 * Example-data preview for the tracing empty state: the waterfall of one slow
 * checkout request, and the details of its dominant span. Clicking the long
 * payment span highlights it and fills the detail card with its attributes.
 * One hidden checkbox drives it via `:checked ~` styles - no timers or state,
 * per the preview rules in the `building-product-empty-states` skill. Detail
 * states crossfade in `__swap` grids, so nothing shifts.
 */
export function TracingPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('TracingPreview', isStatic && 'TracingPreview--static')}>
            {/* Selection state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="tracing-preview-select" className="TracingPreview__checkbox" />

            <div className="TracingPreview__waterfall">
                <div className="TracingPreview__head">
                    <span className="TracingPreview__title">
                        <span className="TracingPreview__live-dot" aria-hidden="true" />
                        POST /api/checkout · 812 ms
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="TracingPreview__rows">
                    {SPAN_ROWS.map((span) => {
                        const rowInner = (
                            <>
                                <span
                                    className="TracingPreview__span-label"
                                    style={{ paddingLeft: `${span.depth * 0.75}rem` }}
                                >
                                    <span className="TracingPreview__service">{span.service}</span>
                                    <span className="TracingPreview__span-name">{span.name}</span>
                                </span>
                                <span className="TracingPreview__track">
                                    <span
                                        className="TracingPreview__bar"
                                        style={{ left: `${span.offset}%`, width: `${span.width}%` }}
                                    />
                                </span>
                                <span className="TracingPreview__duration">{span.duration}</span>
                            </>
                        )
                        if (span.hero) {
                            return (
                                <label
                                    key={span.name}
                                    htmlFor="tracing-preview-select"
                                    className="TracingPreview__row TracingPreview__row--hero"
                                >
                                    {rowInner}
                                </label>
                            )
                        }
                        return (
                            <div key={span.name} className="TracingPreview__row">
                                {rowInner}
                            </div>
                        )
                    })}
                </div>

                <div className="TracingPreview__hint TracingPreview__swap">
                    <span className="TracingPreview__when-idle">Click the longest span to see why it's slow.</span>
                    <span className="TracingPreview__when-selected">
                        79% of this request is the payment call. Click again to deselect.
                    </span>
                </div>
            </div>

            <div className="TracingPreview__detail">
                <div className="TracingPreview__head">
                    <span className="TracingPreview__title">Span details</span>
                    <span className="TracingPreview__fresh TracingPreview__when-selected">payment-provider</span>
                </div>
                <div className="TracingPreview__detail-body TracingPreview__swap">
                    <div className="TracingPreview__detail-hint TracingPreview__when-idle">
                        Select a span to inspect its attributes.
                    </div>
                    <div className="TracingPreview__attrs TracingPreview__when-selected">
                        <div className="TracingPreview__attr">
                            <span className="TracingPreview__attr-key">service.name</span>
                            <span className="TracingPreview__attr-val">payment-provider</span>
                        </div>
                        <div className="TracingPreview__attr">
                            <span className="TracingPreview__attr-key">duration</span>
                            <span className="TracingPreview__attr-val TracingPreview__attr-val--slow">
                                640 ms · 79% of trace
                            </span>
                        </div>
                        <div className="TracingPreview__attr">
                            <span className="TracingPreview__attr-key">http.status_code</span>
                            <span className="TracingPreview__attr-val">200</span>
                        </div>
                        <div className="TracingPreview__attr">
                            <span className="TracingPreview__attr-key">retry.count</span>
                            <span className="TracingPreview__attr-val">2</span>
                        </div>
                        <div className="TracingPreview__attr">
                            <span className="TracingPreview__attr-key">peer.service</span>
                            <span className="TracingPreview__attr-val">payments.example.com</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
