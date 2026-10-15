import { useActions, useValues } from 'kea'
import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import useResizeObserver from 'use-resize-observer'

import { IconCamera, IconChevronLeft, IconChevronRight, IconEllipsis, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonMenu, Spinner, Tooltip } from '@posthog/lemon-ui'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { dayjs } from 'lib/dayjs'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { dateFilterToText } from 'lib/utils/dateFilters'

import { pageHistoryCaptureLogic } from './pageHistoryCaptureLogic'
import { pageHistoryLogic } from './pageHistoryLogic'
import { PageHistoryRangeEditor } from './PageHistoryRangeEditor'
import { PageHistoryTile } from './PageHistoryTile'
import { formatCaptureDay, formatCaptureTimestamp, formatHistoryDateRange } from './pageHistoryUtils'

export function PageHistoryStrip({ id }: { id: string }): JSX.Element {
    const logic = pageHistoryLogic({ id })
    const {
        history,
        historyLoading,
        historyLoadFailed,
        captures,
        usableCaptures,
        visibleCaptures,
        historyPage,
        historyPageCount,
        historyExpanded,
        selectedDateRange,
        isCombinedRange,
        selectedBackground,
        historyBrowseDisabledReason,
        missingCaptureDate,
        missingDateAlternatives,
        navigationNotice,
    } = useValues(logic)
    const {
        browseCapture,
        selectCapture,
        clearSelection,
        loadHistory,
        setHistoryPage,
        setHistoryExpanded,
        setMissingCaptureDate,
    } = useActions(logic)
    const captureLogic = pageHistoryCaptureLogic({ id })
    const { capturing, captureError, captureStatusUnknown, completedCapture, captureNowDisabledReason, todaysCapture } =
        useValues(captureLogic)
    const { requestCapture, setCompletedRequestId } = useActions(captureLogic)
    const { effectiveCommonFilters } = useValues(heatmapDataLogic({ context: 'in-app' }))
    const contextRef = useRef<HTMLElement | null>(null)
    const [browserMaxHeight, setBrowserMaxHeight] = useState(640)
    const measureBrowserSpace = useCallback((): void => {
        const top = contextRef.current?.getBoundingClientRect().top
        if (top !== undefined) {
            setBrowserMaxHeight(Math.max(280, window.innerHeight - Math.max(0, top) - 16))
        }
    }, [])
    const { ref: observeContext } = useResizeObserver<HTMLElement>({ onResize: measureBrowserSpace })
    const setContextRef = useCallback(
        (node: HTMLElement | null): void => {
            contextRef.current = node
            observeContext(node)
        },
        [observeContext]
    )
    useLayoutEffect(() => {
        if (!historyExpanded) {
            return
        }
        measureBrowserSpace()
        window.addEventListener('resize', measureBrowserSpace)
        return () => window.removeEventListener('resize', measureBrowserSpace)
    }, [measureBrowserSpace, historyExpanded])
    const browseRef = useRef<HTMLButtonElement | null>(null)
    const focusCloseButton = useCallback((node: HTMLButtonElement | null): void => {
        node?.focus({ preventScroll: true })
    }, [])
    const closeBrowser = (): void => {
        setHistoryExpanded(false)
        browseRef.current?.focus({ preventScroll: true })
    }
    const captureLabel = todaysCapture ? "Update today's screenshot" : "Capture today's screenshot"

    return (
        <section
            ref={setContextRef}
            className="@container/history p-3 border-b"
            aria-label="Page history"
            data-attr="heatmap-page-history"
            onKeyDown={(event) => {
                if (event.key === 'Escape' && historyExpanded) {
                    event.preventDefault()
                    closeBrowser()
                }
            }}
        >
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <div
                        className="text-sm font-semibold"
                        aria-live="polite"
                        data-attr="heatmap-page-history-selection"
                    >
                        <span>
                            {selectedDateRange
                                ? `Interactions: ${formatHistoryDateRange(selectedDateRange)}`
                                : `Interactions: ${dateFilterToText(effectiveCommonFilters?.date_from, effectiveCommonFilters?.date_to, 'Current date filters')}`}
                        </span>
                        {selectedBackground ? (
                            <span className="sr-only">{`. Screenshot captured ${formatCaptureTimestamp(selectedBackground)}.`}</span>
                        ) : null}
                    </div>
                    <div className="text-xs text-muted mt-1">
                        <Tooltip
                            title={
                                selectedBackground
                                    ? 'Daily screenshots show the page at capture time. They may not reflect later changes or personalized versions.'
                                    : 'This saved screenshot may differ from the pages seen during your interaction dates. Browse screenshots to inspect a past day.'
                            }
                        >
                            <span className="cursor-help border-b border-dashed">
                                {selectedBackground
                                    ? `Screenshot captured ${formatCaptureTimestamp(selectedBackground)} · ${selectedBackground.width}px`
                                    : 'Current saved screenshot'}
                            </span>
                        </Tooltip>
                    </div>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    <LemonButton
                        ref={browseRef}
                        size="small"
                        type="secondary"
                        onClick={() => {
                            if (historyExpanded) {
                                closeBrowser()
                            } else {
                                setHistoryExpanded(true)
                            }
                        }}
                        aria-expanded={historyExpanded}
                        aria-controls="heatmap-history-browser"
                        disabledReason={historyBrowseDisabledReason}
                        data-attr="heatmap-page-history-toggle"
                    >
                        Browse screenshots
                    </LemonButton>
                    {selectedDateRange ? (
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={clearSelection}
                            data-attr="heatmap-page-history-current"
                            aria-label="Current view"
                            tooltip="Restore your current screenshot, date filters, and screen width"
                        >
                            Current view
                        </LemonButton>
                    ) : null}
                    {captures.length > 0 ? (
                        <LemonMenu
                            items={[
                                {
                                    label: captureLabel,
                                    icon: <IconCamera />,
                                    onClick: () => requestCapture(),
                                    disabledReason: captureNowDisabledReason,
                                    'data-attr': 'heatmap-page-history-capture-now',
                                },
                                {
                                    label: 'Refresh screenshots',
                                    icon: <IconRefresh />,
                                    onClick: () => loadHistory(),
                                    disabledReason: historyLoading ? 'Refreshing screenshots' : undefined,
                                    'data-attr': 'heatmap-page-history-refresh',
                                },
                            ]}
                        >
                            <LemonButton
                                size="small"
                                icon={<IconEllipsis />}
                                loading={capturing}
                                aria-label="Screenshot actions"
                                data-attr="heatmap-page-history-actions"
                            />
                        </LemonMenu>
                    ) : null}
                </div>
            </div>
            {isCombinedRange && selectedDateRange ? (
                <LemonBanner
                    type="warning"
                    className="mt-2"
                    action={{
                        children: 'Review days individually',
                        onClick: () => {
                            if (selectedBackground) {
                                selectCapture(selectedBackground.id)
                            }
                        },
                    }}
                >
                    All interactions are positioned on this screenshot. Page changes during this period can move clicks
                    onto different elements.
                </LemonBanner>
            ) : null}
            {historyLoadFailed ? (
                <LemonBanner
                    type="error"
                    className="mt-2"
                    action={{
                        children: 'Try again',
                        onClick: () => loadHistory(),
                        loading: historyLoading,
                        'data-attr': 'heatmap-page-history-retry',
                    }}
                >
                    {history
                        ? "Couldn't refresh screenshots. The available captures may be out of date."
                        : "Couldn't load page history. Try again."}
                </LemonBanner>
            ) : null}
            <div role="status" aria-live="polite">
                {captureStatusUnknown ? (
                    <LemonBanner
                        type="warning"
                        className="mt-2"
                        action={{ children: 'Check capture', onClick: () => loadHistory(), loading: historyLoading }}
                    >
                        Couldn't check the capture's status. It may still be running. Check again before starting
                        another.
                    </LemonBanner>
                ) : captureError ? (
                    <LemonBanner
                        type="error"
                        className="mt-2"
                        action={{
                            children: 'Try again',
                            onClick: () => requestCapture(),
                            disabledReason: captureNowDisabledReason,
                        }}
                    >
                        {captureError}
                    </LemonBanner>
                ) : capturing ? (
                    <div className="flex items-center gap-2 text-sm mt-2">
                        <Spinner className="shrink-0" />
                        <span>Capturing today's page. You can keep exploring history.</span>
                    </div>
                ) : completedCapture ? (
                    <LemonBanner
                        type="success"
                        className="mt-2"
                        onClose={() => setCompletedRequestId(null)}
                        action={{
                            children: 'View capture',
                            onClick: () => {
                                browseCapture(completedCapture.id)
                                setCompletedRequestId(null)
                            },
                        }}
                    >
                        <span>{`Your ${dayjs(completedCapture.captured_on).format('MMM D')} screenshot is ready.`}</span>
                    </LemonBanner>
                ) : null}
                {navigationNotice ? <p className="text-xs text-muted mt-2 mb-0">{navigationNotice}</p> : null}
            </div>
            {missingCaptureDate ? (
                <LemonBanner type="info" className="mt-2" onClose={() => setMissingCaptureDate(null)}>
                    <p className="mb-1">
                        <span>{`No screenshot was saved for ${formatCaptureDay(missingCaptureDate)}. ${selectedBackground ? `Still viewing the ${dayjs(selectedBackground.captured_on).format('MMM D')} screenshot${isCombinedRange ? ' with your combined interaction dates' : ' and its interaction day'}.` : 'Your current view is unchanged.'}`}</span>
                    </p>
                    <p className="text-xs mb-2">A missing screenshot does not indicate whether interactions exist.</p>
                    <div className="flex flex-wrap gap-2">
                        {missingDateAlternatives.map((capture) => (
                            <LemonButton
                                key={capture.id}
                                size="small"
                                type="secondary"
                                onClick={() => browseCapture(capture.id)}
                            >
                                <span>{`Inspect ${formatCaptureDay(capture.captured_on)}`}</span>
                            </LemonButton>
                        ))}
                    </div>
                </LemonBanner>
            ) : null}
            {historyBrowseDisabledReason ? (
                <LemonBanner type="info" className="mt-2">
                    {historyBrowseDisabledReason}
                </LemonBanner>
            ) : null}
            {!history && !historyLoadFailed ? (
                <LemonSkeleton className="h-8 mt-2" />
            ) : history && captures.length === 0 ? (
                <div className="mt-3" data-attr="heatmap-page-history-empty">
                    <p className="text-sm mb-2">
                        {history.storage_available
                            ? "Automatic captures build history for recently viewed pages. Earlier page designs can't be recovered."
                            : 'Screenshot storage is unavailable on this installation. Ask your administrator to configure it.'}
                    </p>
                    <LemonButton
                        size="small"
                        type="primary"
                        icon={<IconCamera />}
                        onClick={requestCapture}
                        loading={capturing}
                        disabledReason={captureNowDisabledReason}
                        data-attr="heatmap-page-history-capture-now"
                    >
                        Capture today's screenshot
                    </LemonButton>
                    <p className="text-xs text-muted mb-0 mt-2">
                        <span>{`Saved screenshots are kept for ${history.retention_days} days. Some days may be missing.`}</span>
                    </p>
                </div>
            ) : null}
            {selectedDateRange ? (
                <p className="text-xs text-muted mt-2 mb-0">
                    This history view is temporary. The heatmap link opens the current view; historical export is
                    unavailable.
                </p>
            ) : null}
            {historyExpanded ? (
                <div
                    className="absolute top-0 inset-x-3 h-full pointer-events-none z-20"
                    style={{ maxHeight: browserMaxHeight }}
                >
                    <div
                        className="absolute bottom-3 inset-x-0 max-w-lg ml-auto pointer-events-auto"
                        id="heatmap-history-browser"
                        role="dialog"
                        aria-labelledby="heatmap-history-browser-title"
                    >
                        <LemonCard hoverEffect={false} className="p-3 shadow-lg">
                            <div className="flex justify-between items-center gap-2">
                                <h3 id="heatmap-history-browser-title" className="text-sm mb-0">
                                    Browse screenshots
                                </h3>
                                <LemonButton
                                    ref={focusCloseButton}
                                    size="small"
                                    onClick={closeBrowser}
                                    aria-label="Close screenshot browser"
                                >
                                    Close
                                </LemonButton>
                            </div>
                            <p className="text-xs text-muted mt-2 mb-2">
                                Choose a day to inspect its interactions and captured screenshot.
                            </p>
                            {visibleCaptures.length > 0 ? (
                                <div className="grid grid-cols-4 gap-2" aria-label="Available screenshot dates">
                                    {visibleCaptures.map((capture) => (
                                        <PageHistoryTile
                                            key={capture.id}
                                            capture={capture}
                                            selected={selectedBackground?.id === capture.id}
                                            disabledReason={historyBrowseDisabledReason}
                                            onSelect={() => browseCapture(capture.id)}
                                        />
                                    ))}
                                </div>
                            ) : (
                                <p className="text-sm">
                                    {historyLoadFailed
                                        ? "Couldn't load screenshots. Use Try again above."
                                        : historyLoading
                                          ? 'Loading screenshots…'
                                          : 'No screenshots are available yet.'}
                                </p>
                            )}
                            {historyPageCount > 1 ? (
                                <div className="flex justify-between gap-2 mt-2">
                                    <LemonButton
                                        size="small"
                                        icon={<IconChevronLeft />}
                                        onClick={() => setHistoryPage(historyPage + 1)}
                                        disabledReason={
                                            historyPage >= historyPageCount - 1
                                                ? 'These are the oldest captures.'
                                                : undefined
                                        }
                                        data-attr="heatmap-page-history-older"
                                    >
                                        Older
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        sideIcon={<IconChevronRight />}
                                        onClick={() => setHistoryPage(historyPage - 1)}
                                        disabledReason={
                                            historyPage === 0 ? 'These are the newest captures.' : undefined
                                        }
                                        data-attr="heatmap-page-history-newer"
                                    >
                                        Newer
                                    </LemonButton>
                                </div>
                            ) : null}
                            <p className="text-xs text-muted mb-0 mt-2">
                                <span>
                                    {usableCaptures.length
                                        ? `${usableCaptures.length} captured ${usableCaptures.length === 1 ? 'day' : 'days'} between ${dayjs(usableCaptures[0].captured_on).format('MMM D')} and ${formatCaptureDay(usableCaptures.at(-1)!.captured_on)}. Kept for ${history?.retention_days} days; some days may be missing.`
                                        : 'Earlier page designs cannot be recovered.'}
                                </span>
                            </p>
                        </LemonCard>
                    </div>
                </div>
            ) : null}
            <PageHistoryRangeEditor id={id} />
        </section>
    )
}
