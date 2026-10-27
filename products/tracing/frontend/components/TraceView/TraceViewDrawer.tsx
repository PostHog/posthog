import { BindLogic, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconCollapse45, IconExpand45, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer/LemonDrawer'
import { pluralize } from 'lib/utils/strings'

import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { traceViewLogic } from './traceViewLogic'

export interface TraceViewDrawerProps {
    viewId: string
    traceId: string | null
    isOpen: boolean
    onClose: () => void
    inspectorOpen: boolean
    onToggleInspector: () => void
    isFullscreen: boolean
    onToggleFullscreen: () => void
    shortcuts: React.ReactNode
    headerActions?: React.ReactNode
    footerActions?: React.ReactNode
    /** Draw over other modals and popovers, for a drawer opened from inside one. */
    forceAbovePopovers?: boolean
    'data-attr': string
    children: React.ReactNode
}

export function TraceViewDrawer({
    viewId,
    traceId,
    isOpen,
    onClose,
    inspectorOpen,
    onToggleInspector,
    isFullscreen,
    onToggleFullscreen,
    shortcuts,
    headerActions,
    footerActions,
    forceAbovePopovers = false,
    'data-attr': dataAttr,
    children,
}: TraceViewDrawerProps): JSX.Element {
    const { summary, timeline } = useValues(traceViewLogic({ id: viewId }))
    // The drawer can sit above popovers, so the inspector's menus, and the person popover, portal inside it.
    const [floatingContainer, setFloatingContainer] = useState<HTMLDivElement | null>(null)
    const floatingContainerRef = useCallback((el: HTMLDivElement | null) => setFloatingContainer(el), [])

    return (
        <LemonDrawer
            isOpen={isOpen}
            onClose={onClose}
            width={isFullscreen ? '100vw' : '90vw'}
            resizable={!isFullscreen}
            resizerLogicKey="trace-view-drawer"
            forceAbovePopovers={forceAbovePopovers}
            data-attr={dataAttr}
            title={<span translate="no">{summary.rootSpan?.name ?? 'Trace'}</span>}
            description={
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs" translate="no">
                        {traceId}
                    </span>
                    {summary.spanCount > 0 && (
                        <>
                            <LemonTag>{formatDuration(timeline.durationUs * 1_000)}</LemonTag>
                            <LemonTag>
                                {pluralize(summary.spanCount, 'span')} · {pluralize(summary.serviceCount, 'service')}
                            </LemonTag>
                            {summary.errorCount > 0 && (
                                <LemonTag type="danger">{pluralize(summary.errorCount, 'error')}</LemonTag>
                            )}
                        </>
                    )}
                    {headerActions}
                </div>
            }
            footer={
                <div className="flex flex-wrap items-center justify-between gap-2 w-full">
                    {shortcuts}
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            icon={inspectorOpen ? <IconSidebarClose /> : <IconSidebarOpen />}
                            tooltip={inspectorOpen ? 'Hide span details' : 'Show span details'}
                            onClick={onToggleInspector}
                            data-attr={`${dataAttr}-toggle-inspector`}
                        />
                        <LemonButton
                            type="secondary"
                            icon={isFullscreen ? <IconCollapse45 /> : <IconExpand45 />}
                            tooltip={isFullscreen ? 'Exit full screen' : 'Full screen'}
                            onClick={onToggleFullscreen}
                            data-attr={`${dataAttr}-toggle-fullscreen`}
                        />
                        {footerActions}
                    </div>
                </div>
            }
        >
            <FloatingContainerContext.Provider value={floatingContainer}>
                <BindLogic logic={traceViewLogic} props={{ id: viewId }}>
                    <div className="flex flex-col gap-2 h-full">{children}</div>
                </BindLogic>
                <div ref={floatingContainerRef} />
            </FloatingContainerContext.Provider>
        </LemonDrawer>
    )
}
