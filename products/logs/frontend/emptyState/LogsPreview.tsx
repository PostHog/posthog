import './LogsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

interface LogRow {
    time: string
    level: 'info' | 'warn' | 'error'
    message: string
}

const LOG_ROWS: LogRow[] = [
    { time: '12:04:01', level: 'info', message: 'checkout-api request completed in 42 ms' },
    { time: '12:04:03', level: 'info', message: 'web cache hit for /api/products' },
    { time: '12:04:07', level: 'warn', message: 'checkout-api retrying payment provider call (attempt 2)' },
    { time: '12:04:09', level: 'error', message: 'checkout-api payment failed: card_declined' },
    { time: '12:04:11', level: 'info', message: 'web GET /api/products 200' },
    { time: '12:04:12', level: 'error', message: 'checkout-api upstream timeout after 3000 ms' },
]

/**
 * Example-data preview for the logs empty state: a live log stream and the detail
 * panel of its failing request. Clicking the "errors" filter chip dims everything
 * but the error lines and fills the detail panel with the failing request's
 * attributes. One hidden checkbox drives it via `:checked ~` styles - no timers or
 * state, per the preview rules in the `building-product-empty-states` skill.
 * Filtering dims rows in place and detail states crossfade in `__swap` grids, so
 * nothing shifts.
 */
export function LogsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('LogsPreview', isStatic && 'LogsPreview--static')}>
            {/* Filter state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="logs-preview-filter" className="LogsPreview__checkbox" />

            <div className="LogsPreview__stream">
                <div className="LogsPreview__head">
                    <span className="LogsPreview__title">
                        <span className="LogsPreview__live-dot" aria-hidden="true" />
                        Live logs
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="LogsPreview__filters">
                    <span className="LogsPreview__chip LogsPreview__chip--passive">service: all</span>
                    <label htmlFor="logs-preview-filter" className="LogsPreview__chip LogsPreview__chip--level">
                        <span className="LogsPreview__chip-dot" aria-hidden="true" />
                        errors only
                    </label>
                    <span className="LogsPreview__result-count LogsPreview__swap">
                        <span className="LogsPreview__when-all">1,204 lines</span>
                        <span className="LogsPreview__when-errors">2 lines</span>
                    </span>
                </div>

                <div className="LogsPreview__rows">
                    {LOG_ROWS.map((row) => (
                        <div
                            key={`${row.time}-${row.message}`}
                            className={cn('LogsPreview__row', `LogsPreview__row--${row.level}`)}
                        >
                            <span className="LogsPreview__time">{row.time}</span>
                            <span className={cn('LogsPreview__level', `LogsPreview__level--${row.level}`)}>
                                {row.level}
                            </span>
                            <span className="LogsPreview__message">{row.message}</span>
                        </div>
                    ))}
                    <div className="LogsPreview__row LogsPreview__row--cursor" aria-hidden="true">
                        <span className="LogsPreview__time">12:04:13</span>
                        <span className="LogsPreview__caret" />
                    </div>
                </div>
            </div>

            <div className="LogsPreview__detail">
                <div className="LogsPreview__head">
                    <span className="LogsPreview__title">Log attributes</span>
                    <span className="LogsPreview__fresh LogsPreview__when-errors">filtered</span>
                </div>
                <div className="LogsPreview__detail-body LogsPreview__swap">
                    <div className="LogsPreview__detail-hint LogsPreview__when-all">
                        Filter to errors only to inspect the failing request.
                    </div>
                    <div className="LogsPreview__attrs LogsPreview__when-errors">
                        <div className="LogsPreview__attr">
                            <span className="LogsPreview__attr-key">service.name</span>
                            <span className="LogsPreview__attr-val">checkout-api</span>
                        </div>
                        <div className="LogsPreview__attr">
                            <span className="LogsPreview__attr-key">severity</span>
                            <span className="LogsPreview__attr-val LogsPreview__attr-val--error">error</span>
                        </div>
                        <div className="LogsPreview__attr">
                            <span className="LogsPreview__attr-key">http.status_code</span>
                            <span className="LogsPreview__attr-val">502</span>
                        </div>
                        <div className="LogsPreview__attr">
                            <span className="LogsPreview__attr-key">trace_id</span>
                            <span className="LogsPreview__attr-val">4f2a91c3d8b0</span>
                        </div>
                        <div className="LogsPreview__attr">
                            <span className="LogsPreview__attr-key">body</span>
                            <span className="LogsPreview__attr-val">payment failed: card_declined</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
