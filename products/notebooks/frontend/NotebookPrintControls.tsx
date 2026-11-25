import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/retryImport'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { notebookExportLogic } from './notebookExportLogic'

const NotebookImageExportControls = lazyWithRetry(() =>
    import('./NotebookImageExportControls').then(({ NotebookImageExportControls }) => ({
        default: NotebookImageExportControls,
    }))
)

export function NotebookPrintControls({ shortId }: { shortId: string }): JSX.Element | null {
    const { preparingPrint, exportFormat } = useValues(notebookExportLogic({ shortId }))
    const { notebook } = useValues(notebookLogic({ shortId }))
    const { printNotebook, cancelPrint } = useActions(notebookExportLogic({ shortId }))
    if (!preparingPrint) {
        return null
    }
    if (exportFormat === 'png') {
        return (
            <Suspense fallback={null}>
                <NotebookImageExportControls
                    shortId={shortId}
                    title={notebook?.title || 'Notebook'}
                    onCancel={cancelPrint}
                />
            </Suspense>
        )
    }
    return (
        <LemonBanner type="info" className="Notebook__print-controls mb-4">
            <p>Review the notebook's results before printing. Charts outside the screen are loading too.</p>
            <p>Choose “Save as PDF” in the print dialog to download a PDF.</p>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    onClick={() => printNotebook(notebook?.title || 'Notebook')}
                    data-attr="notebook-confirm-print"
                >
                    Print
                </LemonButton>
                <LemonButton type="secondary" onClick={cancelPrint} data-attr="notebook-cancel-print">
                    Cancel
                </LemonButton>
            </div>
        </LemonBanner>
    )
}
