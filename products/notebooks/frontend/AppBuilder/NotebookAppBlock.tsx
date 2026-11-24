import { IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { MarkdownNotebook } from 'lib/components/MarkdownNotebook'
import { ComponentPanelContext } from 'lib/components/MarkdownNotebook/componentPanelContext'
import { serializeNode } from 'lib/components/MarkdownNotebook/markdown'
import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { NOTEBOOK_MARKDOWN_REGISTRY } from 'scenes/notebooks/Notebook/markdownNotebookRegistry'
import type { NotebookVariable, NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { NotebookAppInput } from './NotebookAppInput'
import { appCellMarkdown } from './notebookAppLayout'

export function NotebookAppBlock({
    block,
    cell,
    stale,
    onSource,
    variables,
    canInteract,
    onInput,
    onCellOutput,
}: {
    block: NotebookAppBlockApi
    cell?: NotebookBlockNode
    stale: boolean
    onSource?: (id: string) => void
    variables: NotebookVariable[]
    canInteract: boolean
    onInput: (name: string, value: NotebookVariableValue) => void
    onCellOutput: (nodeId: string, markdown: string) => void
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
                        onChange={canInteract ? (markdown) => onCellOutput(cell.id, markdown) : undefined}
                        registry={NOTEBOOK_MARKDOWN_REGISTRY}
                        mode="view"
                        className="NotebookAppBuilder__cell"
                    />
                </ComponentPanelContext.Provider>
            )}
        </div>
    )
}
