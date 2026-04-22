import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer'

import { logsViewerModalLogic } from './logsViewerModalLogic'

export function LogsViewerModal(): JSX.Element | null {
    const { isOpen, viewerId, fullScreen, initialFilters } = useValues(logsViewerModalLogic)
    const { closeLogsViewerModal } = useActions(logsViewerModalLogic)
    const [floatingContainer, setFloatingContainer] = useState<HTMLDivElement | null>(null)
    const floatingContainerRef = useCallback((el: HTMLDivElement | null) => setFloatingContainer(el), [])

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeLogsViewerModal}
            simple
            title=""
            fullScreen={fullScreen}
            forceAbovePopovers
            hideCloseButton
            className={fullScreen ? 'bg-primary' : 'bg-primary h-[calc(100vh-60px-2rem)]'}
            width={fullScreen ? undefined : '90vw'}
            maxWidth={fullScreen ? undefined : 1600}
        >
            <FloatingContainerContext.Provider value={floatingContainer}>
                <div className="flex items-center justify-end border-b px-1 py-0.5">
                    <LemonButton icon={<IconX />} size="small" onClick={closeLogsViewerModal} tooltip="Close" />
                </div>
                <LemonModal.Content embedded className="flex flex-col flex-1 min-h-0 overflow-x-hidden">
                    <div className="flex-1 min-h-0 overflow-hidden p-2">
                        <LogsViewer
                            id={viewerId}
                            showFullScreenButton={false}
                            initialFilters={initialFilters ?? undefined}
                        />
                    </div>
                </LemonModal.Content>
                <div ref={floatingContainerRef} />
            </FloatingContainerContext.Provider>
        </LemonModal>
    )
}
