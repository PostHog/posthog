import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { reusableWidgetLogic } from './reusableWidgetLogic'

export function ReusableWidgetSourceModal({ widgetId }: { widgetId: string }): JSX.Element {
    const logic = reusableWidgetLogic({ widgetId })
    const { source, sourceError, sourceLoading, sourceModalOpen } = useValues(logic)
    const { closeSourceModal, loadSource } = useActions(logic)

    return (
        <LemonModal
            isOpen={sourceModalOpen}
            onClose={closeSourceModal}
            title="Reusable widget source"
            width="70vw"
            footer={<LemonButton onClick={closeSourceModal}>Close</LemonButton>}
        >
            {sourceLoading ? (
                <LemonSkeleton className="h-80 w-full" />
            ) : sourceError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadSource }}>
                    We couldn't load this widget's source.
                </LemonBanner>
            ) : source !== null ? (
                <CodeEditorResizeable
                    className="ph-no-capture"
                    language="typescript"
                    value={source}
                    minHeight="20rem"
                    maxHeight="60vh"
                    allowManualResize={false}
                    options={{ readOnly: true, minimap: { enabled: false } }}
                />
            ) : null}
        </LemonModal>
    )
}
