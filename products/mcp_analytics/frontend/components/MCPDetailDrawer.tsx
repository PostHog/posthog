import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { IconChevronDown, IconExpand45, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import {
    DetailPanel,
    isDetailPanelFullWidth,
} from 'products/ai_observability/frontend/redesign/shared/components/DetailPanel'
import {
    isOverlayOpen,
    shouldCloseOnEscape,
} from 'products/ai_observability/frontend/redesign/trace/shouldCloseOnEscape'

export interface MCPDetailDrawerPosition {
    index: number
    total: number
}

export interface MCPDetailDrawerProps {
    /** Lowercase row noun for labels, e.g. "tool call". */
    noun: string
    title: ReactNode
    /** Null when the open item is not in the loaded rows. */
    position: MCPDetailDrawerPosition | null
    onPrevious: (() => void) | null
    onNext: (() => void) | null
    /** Leave it out when the list is already the item's page. */
    fullPageHref?: string
    fullPageLabel?: string
    /** An arrow when the link leaves this page. */
    fullPageIcon?: JSX.Element
    /** Over another drawer; Escape closes only this one. */
    stacked?: boolean
    onClose: () => void
    'data-attr': string
    children: ReactNode
}

// Stacked drawers all listen on window and run in registration order, so only the drawer opened last handles Escape.
const openDrawers: object[] = []

/** List detail drawer, matching the AI observability trace drawer. */
export function MCPDetailDrawer({
    noun,
    title,
    position,
    onPrevious,
    onNext,
    fullPageHref,
    fullPageLabel = 'Open full page',
    fullPageIcon = <IconExpand45 />,
    stacked = false,
    onClose,
    'data-attr': dataAttr,
    children,
}: MCPDetailDrawerProps): JSX.Element | null {
    const { mainContentRect } = useValues(panelLayoutLogic)
    const { setLayoutNavCollapsedOverride } = useActions(panelLayoutLogic)
    const { setSidebarOpen } = useActions(todayShellLogic)
    const containerRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef,
        logicKey: 'mcp-analytics-drawer',
        placement: 'left',
        persistent: true,
        minSize: 480,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))

    // Don't step under a modal opened from the content.
    useShortcut({
        name: 'MCPDetailDrawerPrevious',
        keybind: [['p']],
        intent: `Previous ${noun}`,
        interaction: 'function',
        callback: () => !isOverlayOpen() && onPrevious?.(),
        disabled: !onPrevious,
    })
    useShortcut({
        name: 'MCPDetailDrawerNext',
        keybind: [['n']],
        intent: `Next ${noun}`,
        interaction: 'function',
        callback: () => !isOverlayOpen() && onNext?.(),
        disabled: !onNext,
    })
    // Collapse the nav and close the sidebar for room while open, and put both back on close.
    // The drawer under a stacked one owns this.
    useEffect(() => {
        if (stacked) {
            return
        }
        const sidebarWasOpen = todayShellLogic.values.sidebarOpen
        setLayoutNavCollapsedOverride(dataAttr, true)
        setSidebarOpen(false)
        return () => {
            setLayoutNavCollapsedOverride(dataAttr, null)
            if (sidebarWasOpen && !todayShellLogic.values.sidebarOpen) {
                setSidebarOpen(true)
            }
        }
    }, [stacked, dataAttr, setLayoutNavCollapsedOverride, setSidebarOpen])
    useEffect(() => {
        openDrawers.push(containerRef)
        return () => void openDrawers.splice(openDrawers.indexOf(containerRef), 1)
    }, [])
    useEffect(() => {
        const closeOnEscape = (event: KeyboardEvent): void => {
            if (openDrawers[openDrawers.length - 1] === containerRef && shouldCloseOnEscape(event)) {
                onClose()
                if (stacked) {
                    event.preventDefault()
                }
            }
        }
        // A stacked drawer listens in the capture phase on window, ahead of the document listener of the drawer under it.
        const target = stacked ? window : document
        target.addEventListener('keydown', closeOnEscape as EventListener, stacked)
        return () => target.removeEventListener('keydown', closeOnEscape as EventListener, stacked)
    }, [onClose, stacked])

    if (!mainContentRect) {
        return null
    }

    const notInListReason = `This ${noun} isn't in the list`
    return (
        <DetailPanel
            aria-label={`${noun[0].toUpperCase()}${noun.slice(1)} detail`}
            data-attr={dataAttr}
            rect={mainContentRect}
            width={desiredSize ?? Math.round(mainContentRect.width * 0.85)}
            containerRef={containerRef}
            resizer={isDetailPanelFullWidth(mainContentRect.width) ? null : <Resizer {...resizerProps} />}
            toolbar={
                <div className="flex min-w-0 flex-1 items-center gap-1">
                    {stacked ? null : (
                        <>
                            <LemonButton
                                size="small"
                                icon={<IconChevronDown className="rotate-180" />}
                                tooltip={
                                    <>
                                        Previous {noun} <KeyboardShortcut p />
                                    </>
                                }
                                aria-label={`Previous ${noun}`}
                                data-attr={`${dataAttr}-previous`}
                                onClick={onPrevious ?? undefined}
                                disabledReason={
                                    onPrevious ? undefined : position ? `This is the first ${noun}` : notInListReason
                                }
                            />
                            <LemonButton
                                size="small"
                                icon={<IconChevronDown />}
                                tooltip={
                                    <>
                                        Next {noun} <KeyboardShortcut n />
                                    </>
                                }
                                aria-label={`Next ${noun}`}
                                data-attr={`${dataAttr}-next`}
                                onClick={onNext ?? undefined}
                                disabledReason={
                                    onNext ? undefined : position ? `This is the last loaded ${noun}` : notInListReason
                                }
                            />
                        </>
                    )}
                    {position ? (
                        <span className="ml-1 whitespace-nowrap text-xs text-secondary" aria-live="polite">
                            {`${position.index + 1} of ${position.total}`}
                        </span>
                    ) : null}
                    <span className="ml-2 min-w-0 truncate text-sm font-semibold">{title}</span>
                    <div className="ml-auto flex items-center gap-1">
                        {fullPageHref ? (
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={fullPageIcon}
                                to={fullPageHref}
                                data-attr={`${dataAttr}-full-page`}
                            >
                                {fullPageLabel}
                            </LemonButton>
                        ) : null}
                        <LemonButton
                            size="small"
                            icon={<IconX />}
                            tooltip={
                                <>
                                    Close <KeyboardShortcut escape />
                                </>
                            }
                            aria-label="Close"
                            data-attr={`${dataAttr}-close`}
                            onClick={onClose}
                        />
                    </div>
                </div>
            }
        >
            {children}
        </DetailPanel>
    )
}
