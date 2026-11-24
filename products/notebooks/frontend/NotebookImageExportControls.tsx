import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { captureImageLogic } from 'lib/components/Scenes/InsightOrDashboard/captureImageLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

const EXPORT_CONTROLS = [
    '.Notebook__image-controls',
    '.NotebookColumn',
    '.MarkdownNotebook__jupyter-input',
    '.MarkdownNotebook__jupyter-prompt',
    '.MarkdownNotebook__jupyter-collapser',
    '.MarkdownNotebook__jupyter-output-area--muted',
    '.MarkdownNotebook__columns-toolbar',
    '.MarkdownNotebook__jupyter-output-area button',
    '.DataVisualization__controls',
    '.MarkdownNotebook__debug-toolbar',
    '.MarkdownNotebook__debug-drawer',
    '.MarkdownNotebook__drag-handle',
    '.MarkdownNotebook__block-comment-button',
    '.MarkdownNotebook__jupyter-add-cell',
    '.MarkdownNotebook__canvas-header',
    '.MarkdownNotebook__component-actions',
    '.MarkdownNotebook__component-mode-actions',
    '.MarkdownNotebook__component-toolbar-controls',
    '.MarkdownNotebook__component-panel--filters',
    '.MarkdownNotebook__real-node-resize-handle',
    '.MarkdownNotebook__real-node-settings',
    '.MarkdownNotebook__jupyter-cell-actions',
    '.MarkdownNotebook__line-insert-menu-button',
    '.MarkdownNotebook__insert-boundary-button',
    '.NotebookNode__settings',
    '.NotebookNode__resize-handle',
    '.NotebookNode__meta button',
].join(', ')

export function NotebookImageExportControls({
    shortId,
    title,
    onCancel,
}: {
    shortId: string
    title: string
    onCancel: () => void
}): JSX.Element {
    const { isCapturing } = useValues(captureImageLogic)
    const { downloadImage } = useActions(captureImageLogic)
    return (
        <LemonBanner type="info" className="Notebook__image-controls mb-4">
            <p>Review the notebook's results before exporting. Charts outside the screen are loading too.</p>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    disabled={isCapturing}
                    onClick={() => {
                        const selector = `.Notebook[data-notebook-short-id="${CSS.escape(shortId)}"]`
                        if (document.querySelector(selector)?.querySelector('iframe')) {
                            lemonToast.error('PNG export cannot include embedded frames. Use Print / save PDF instead.')
                            return
                        }
                        downloadImage({
                            selector,
                            excludeSelector: EXPORT_CONTROLS,
                            screenshotKey: `notebook-${shortId}`,
                            name: title,
                            onSuccess: onCancel,
                        })
                    }}
                    data-attr="notebook-confirm-image"
                >
                    {isCapturing ? 'Creating image' : 'Download PNG'}
                </LemonButton>
                <LemonButton disabled={isCapturing} onClick={onCancel}>
                    Cancel
                </LemonButton>
            </div>
        </LemonBanner>
    )
}
