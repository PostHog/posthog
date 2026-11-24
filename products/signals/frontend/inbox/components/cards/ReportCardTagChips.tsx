import clsx from 'clsx'
import { SyntheticEvent, useLayoutEffect, useState } from 'react'

import { LemonDropdown } from '@posthog/lemon-ui'

import { SignalReport } from '../../types'
import { fitReportTagCount } from '../../utils/reportTagFit'
import { ReportTagToggle, useReportTagToggle } from '../badges/useReportTagToggle'

// Matches the `gap-1` between the chips.
const CHIP_GAP_PX = 4

// The negative margin cancels the padding, so the chips give a larger tap target without making the
// line taller than the meta text beside them.
const CHIP_CLASS_NAME = '-my-1 inline-flex min-w-0 max-w-40 items-center rounded px-1 py-1 text-xs leading-none'

function chipClassName(selected: boolean): string {
    return clsx(
        CHIP_CLASS_NAME,
        selected
            ? 'bg-accent-highlight-secondary font-medium text-accent'
            : 'text-tertiary hover:bg-fill-button-tertiary-hover hover:text-primary'
    )
}

// The card is a link, and the wrapper around it starts a multi-select hold on pointer down.
// A chip acts on its own, so neither the report nor a selection hold may start from it.
function stopCardGesture(event: SyntheticEvent): void {
    event.stopPropagation()
}

function TagChip({ tag, toggle }: { tag: string; toggle: ReportTagToggle }): JSX.Element {
    const selected = toggle.isSelected(tag)
    return (
        <button
            type="button"
            aria-pressed={selected}
            disabled={toggle.isDisabled(tag)}
            title={toggle.title(tag)}
            onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                toggle.toggle(tag)
            }}
            className={clsx(chipClassName(selected), 'disabled:cursor-not-allowed enabled:cursor-pointer')}
            data-attr="inbox-report-tag"
        >
            <span className="truncate">{`#${tag}`}</span>
        </button>
    )
}

/**
 * A report's tags on one line of an inbox card, styled like the meta text around them. Each chip
 * adds its tag to the Tags filter or removes it. Tags in the filter are highlighted and lead the
 * line, so the tag a report matched on is never in the overflow. As many tags show as fit the free
 * width, and a `+n` chip opens the rest in a popover, so the card never grows a row for its tags.
 */
export function ReportCardTagChips({ report }: { report: SignalReport }): JSX.Element | null {
    const toggle = useReportTagToggle(report, 'card')
    const { orderedTags, selectedCount } = toggle
    // Callback refs, because the measure only runs once both elements are in the DOM.
    const [container, setContainer] = useState<HTMLDivElement | null>(null)
    const [measure, setMeasure] = useState<HTMLDivElement | null>(null)
    const [visibleCount, setVisibleCount] = useState(orderedTags.length)
    const [overflowOpen, setOverflowOpen] = useState(false)
    const orderKey = orderedTags.join('\n')

    useLayoutEffect(() => {
        if (!container || !measure) {
            return
        }
        const fit = (): void => {
            // A container with no width has no layout to fit, for example while the card is hidden.
            if (container.clientWidth === 0) {
                return
            }
            const widths = Array.from(measure.children, (child) => (child as HTMLElement).offsetWidth)
            const overflowWidth = widths.pop() ?? 0
            setVisibleCount(
                fitReportTagCount({
                    tagWidths: widths,
                    overflowWidth,
                    available: container.clientWidth,
                    gap: CHIP_GAP_PX,
                    minimum: selectedCount,
                })
            )
        }
        fit()
        const observer = new ResizeObserver(fit)
        observer.observe(container)
        return () => observer.disconnect()
    }, [container, measure, orderKey, selectedCount])

    if (orderedTags.length === 0) {
        return null
    }

    const visible = orderedTags.slice(0, visibleCount)
    const hidden = orderedTags.slice(visibleCount)

    return (
        <div
            ref={setContainer}
            // Zero basis and width, so the chips take only the space the line has left and never push
            // the timestamp onto a new line. The minimum width keeps room for the `+n` chip.
            className="relative flex w-0 min-w-8 flex-1 items-center gap-1"
            role="group"
            aria-label="Report tags"
            onPointerDown={stopCardGesture}
        >
            {/* Every chip at its natural width, out of the layout, so the fit can measure the tags it hides. */}
            <div
                ref={setMeasure}
                aria-hidden
                className="pointer-events-none invisible absolute inset-x-0 top-0 flex h-0 gap-1 overflow-hidden"
            >
                {orderedTags.map((tag) => (
                    <span key={tag} className={clsx(chipClassName(toggle.isSelected(tag)), 'shrink-0')}>
                        <span className="truncate">{`#${tag}`}</span>
                    </span>
                ))}
                <span className={clsx(chipClassName(false), 'shrink-0')}>{`+${orderedTags.length}`}</span>
            </div>
            {visible.map((tag) => (
                <TagChip key={tag} tag={tag} toggle={toggle} />
            ))}
            {hidden.length > 0 && (
                <LemonDropdown
                    visible={overflowOpen}
                    onVisibilityChange={setOverflowOpen}
                    overlay={
                        <div
                            className="flex max-w-60 flex-wrap gap-1 p-1"
                            role="group"
                            aria-label="More report tags"
                            onPointerDown={stopCardGesture}
                        >
                            {hidden.map((tag) => (
                                <TagChip key={tag} tag={tag} toggle={toggle} />
                            ))}
                        </div>
                    }
                >
                    <button
                        type="button"
                        aria-label={`Show ${hidden.length} more tags`}
                        aria-expanded={overflowOpen}
                        title={hidden.join(', ')}
                        onClick={(event) => {
                            event.preventDefault()
                            event.stopPropagation()
                        }}
                        className={clsx(chipClassName(false), 'shrink-0 cursor-pointer')}
                        data-attr="inbox-report-tag-overflow"
                    >
                        {`+${hidden.length}`}
                    </button>
                </LemonDropdown>
            )}
        </div>
    )
}
