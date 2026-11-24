import posthog from 'posthog-js'
import { useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Tooltip, lemonToast } from '@posthog/lemon-ui'

import { MarkdownNotebook } from 'lib/components/MarkdownNotebook'
import { ComponentPanelContext } from 'lib/components/MarkdownNotebook/componentPanelContext'
import { serializeNode } from 'lib/components/MarkdownNotebook/markdown'
import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { retryImport } from 'lib/utils/retryImport'
import { reloadAfterChunkLoadError } from 'lib/utils/stableChunks'
import { NOTEBOOK_MARKDOWN_REGISTRY } from 'scenes/notebooks/Notebook/markdownNotebookRegistry'
import type { NotebookVariable, NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import { NodeKind } from '~/queries/schema/schema-general'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { notebookFunnel } from './launchReview'
import { NotebookAppInput } from './NotebookAppInput'
import { appCellMarkdown } from './notebookAppLayout'

function FunnelRecordingsButton({ cell }: { cell: NotebookBlockNode }): JSX.Element | null {
    const [loading, setLoading] = useState(false)
    const funnel = notebookFunnel(cell)
    if (!funnel) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            className="mb-3"
            data-attr="notebook-app-dropoff-recordings"
            loading={loading}
            onClick={async () => {
                setLoading(true)
                let modal: typeof import('scenes/trends/persons-modal/PersonsModal')
                try {
                    modal = await retryImport(() => import('scenes/trends/persons-modal/PersonsModal'))
                } catch (error) {
                    lemonToast.error("Couldn't open drop-off recordings. Reload the page to try again.", {
                        button: { label: 'Reload', action: () => reloadAfterChunkLoadError(error) },
                    })
                    return
                } finally {
                    setLoading(false)
                }
                posthog.capture('notebook app drop-off recordings opened', { step_count: funnel.series.length })
                modal.openPersonsModal({
                    title: 'People who dropped off at the final step',
                    query: {
                        kind: NodeKind.FunnelsActorsQuery,
                        source: funnel,
                        funnelStep: -funnel.series.length,
                        includeRecordings: true,
                    },
                    additionalSelect: { matched_recordings: 'matched_recordings' },
                })
            }}
        >
            View drop-off recordings
        </LemonButton>
    )
}

export function NotebookAppBlock({
    block,
    cell,
    stale,
    onSource,
    variables,
    canInteract,
    onInput,
    onCellOutput,
    renderOutput,
}: {
    block: NotebookAppBlockApi
    cell?: NotebookBlockNode
    stale: boolean
    onSource?: (id: string) => void
    variables: NotebookVariable[]
    canInteract: boolean
    onInput: (name: string, value: NotebookVariableValue) => void
    onCellOutput?: (nodeId: string, markdown: string) => void
    renderOutput?: (cell: NotebookBlockNode) => JSX.Element | undefined
}): JSX.Element {
    if (block.kind === 'divider') {
        return <hr aria-label={block.title || undefined} />
    }
    if (block.kind === 'text') {
        return (
            <div>
                {block.title && <h3 className="mb-3">{block.title}</h3>}
                <LemonMarkdown disableImages="all">{block.text || '*Add text in component settings.*'}</LemonMarkdown>
            </div>
        )
    }
    if (block.kind === 'input') {
        return (
            <NotebookAppInput
                block={block}
                variable={variables.find((variable) => variable.name === block.variable)}
                disabled={!canInteract}
                onChange={(value) => onInput(block.variable || '', value)}
            />
        )
    }
    if (!cell) {
        return (
            <LemonBanner type="warning">
                This source cell is no longer in the notebook. Choose another cell in component settings.
            </LemonBanner>
        )
    }
    const source =
        cell.type === 'component' && typeof cell.props.code === 'string' ? cell.props.code : serializeNode(cell)
    return (
        <div className="min-w-0">
            {(block.title || stale || onSource) && (
                <div className="flex items-center justify-between gap-2 mb-3" data-attr="notebook-app-cell-header">
                    {block.title && <h3 className="mb-0 min-w-0">{block.title}</h3>}
                    <div className="flex items-center gap-2 shrink-0 ml-auto">
                        {stale && (
                            <Tooltip title="Inputs changed. Run all to update the charts and calculated values.">
                                <LemonTag
                                    type="warning"
                                    icon={<IconWarning />}
                                    tabIndex={0}
                                    data-attr="notebook-app-stale"
                                >
                                    STALE
                                </LemonTag>
                            </Tooltip>
                        )}
                        {onSource && (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                icon={<IconOpenInNew />}
                                onClick={() => onSource(cell.id)}
                                tooltip="Open in notebook"
                                aria-label={`Open ${block.title || 'cell'} in notebook`}
                                data-attr="notebook-app-open-source"
                            >
                                Open
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}
            {block.display === 'source' || block.display === 'both' ? (
                <pre className="p-3 rounded bg-surface-secondary overflow-auto text-xs">
                    <code>{source}</code>
                </pre>
            ) : null}
            {block.display !== 'source' && (
                <>
                    <FunnelRecordingsButton cell={cell} />
                    {renderOutput?.(cell) ?? (
                        <ComponentPanelContext.Provider
                            value={{
                                componentPanels: { filters: false, results: true },
                                showEditPanel: false,
                                showViewPanel: true,
                                outputOnly: true,
                            }}
                        >
                            <MarkdownNotebook
                                value={appCellMarkdown(cell)}
                                onChange={
                                    canInteract && onCellOutput
                                        ? (markdown) => onCellOutput(cell.id, markdown)
                                        : undefined
                                }
                                registry={NOTEBOOK_MARKDOWN_REGISTRY}
                                mode="view"
                                className="NotebookAppBuilder__cell"
                            />
                        </ComponentPanelContext.Provider>
                    )}
                </>
            )}
        </div>
    )
}
