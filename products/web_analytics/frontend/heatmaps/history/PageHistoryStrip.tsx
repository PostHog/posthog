import { useActions, useValues } from 'kea'
import { useCallback, useRef } from 'react'

import {
    IconCamera,
    IconChevronLeft,
    IconChevronRight,
    IconClock,
    IconEllipsis,
    IconInfo,
    IconRefresh,
    IconX,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonMenu, Spinner, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { pageHistoryCaptureLogic } from './pageHistoryCaptureLogic'
import { pageHistoryLogic } from './pageHistoryLogic'
import { PageHistoryRangeEditor } from './PageHistoryRangeEditor'
import { PageHistoryTile } from './PageHistoryTile'
import { formatCaptureDay, formatCaptureTimestamp } from './pageHistoryUtils'

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
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2 min-w-0">
                    <IconCamera className="text-muted shrink-0" />
                    <span className="text-sm font-medium" aria-live="polite" data-attr="heatmap-page-history-selection">
                        {selectedBackground
                            ? `Screenshot · ${formatCaptureDay(selectedBackground.captured_on)}`
                            : 'Current screenshot'}
                    </span>
                    <Tooltip
                        title={
                            <div className="max-w-xs">
                                <p>
                                    {selectedBackground
                                        ? `Captured ${formatCaptureTimestamp(selectedBackground)} at ${selectedBackground.width}px.`
                                        : 'Showing the current saved screenshot.'}
                                </p>
                                <p>
                                    Daily screenshots may differ from later changes or personalized pages. Some days may
                                    be missing.
                                </p>
                                <p className="mb-0">{`Screenshots are kept for ${history?.retention_days ?? 90} days. Historical views aren't saved in shared links and can't be exported.`}</p>
                            </div>
                        }
                    >
                        <LemonButton
                            size="xsmall"
                            icon={<IconInfo />}
                            aria-label="About page history"
                            data-attr="heatmap-page-history-info"
                        />
                    </Tooltip>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    <LemonButton
                        ref={browseRef}
                        size="small"
                        type="secondary"
                        icon={<IconClock />}
                        active={historyExpanded}
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
                        Page history
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
                        children: 'View one day',
                        onClick: () => {
                            if (selectedBackground) {
                                selectCapture(selectedBackground.id)
                            }
                        },
                    }}
                >
                    Page changes across these days may misalign clicks on this screenshot.
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
                        Couldn't check this capture. Check its status before starting another.
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
                        <span>Capturing today's screenshot…</span>
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
                    <p className="mb-2">
                        <span>{`No screenshot for ${formatCaptureDay(missingCaptureDate)}. Your current view is unchanged. Interaction data may still be available.`}</span>
                    </p>
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
                            ? 'No page history yet. Capture this page to start saving daily screenshots.'
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
                </div>
            ) : null}
            {historyExpanded ? (
                <LemonCard hoverEffect={false} className="mt-3 p-3 bg-surface-secondary">
                    <div id="heatmap-history-browser" role="region" aria-labelledby="heatmap-history-browser-title">
                        <div className="flex flex-wrap justify-between items-center gap-2 mb-3">
                            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                                <h3 id="heatmap-history-browser-title" className="text-sm mb-0">
                                    Page history
                                </h3>
                                <span className="text-xs text-muted">
                                    {history ? `${usableCaptures.length} screenshots` : 'Loading screenshots…'}
                                </span>
                            </div>
                            <LemonButton
                                ref={focusCloseButton}
                                size="small"
                                icon={<IconX />}
                                onClick={closeBrowser}
                                aria-label="Close screenshot browser"
                            />
                        </div>
                        {visibleCaptures.length > 0 ? (
                            <div
                                className="grid grid-cols-2 @min-[32rem]/history:grid-cols-4 gap-2 max-h-64 overflow-y-auto p-1"
                                aria-label="Available screenshot dates"
                            >
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
                                    disabledReason={historyPage === 0 ? 'These are the newest captures.' : undefined}
                                    data-attr="heatmap-page-history-newer"
                                >
                                    Newer
                                </LemonButton>
                            </div>
                        ) : null}
                    </div>
                </LemonCard>
            ) : null}
            <PageHistoryRangeEditor id={id} />
        </section>
    )
}
