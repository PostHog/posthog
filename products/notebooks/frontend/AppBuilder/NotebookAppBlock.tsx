import { LemonBanner } from '@posthog/lemon-ui'

import { MarkdownNotebook } from 'lib/components/MarkdownNotebook'
import { serializeNode } from 'lib/components/MarkdownNotebook/markdown'
import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { NOTEBOOK_MARKDOWN_REGISTRY } from 'scenes/notebooks/Notebook/markdownNotebookRegistry'
import type { NotebookVariable, NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { NotebookAppInput } from './NotebookAppInput'
import { appCellMarkdown } from './notebookAppLayout'

export function NotebookAppBlock({
    block,
    cell,
    variables,
    canInteract,
    onInput,
}: {
    block: NotebookAppBlockApi
    cell?: NotebookBlockNode
    variables: NotebookVariable[]
    canInteract: boolean
    onInput: (name: string, value: NotebookVariableValue) => void
}): JSX.Element {
    if (block.kind === 'divider') {
        return <hr />
    }
    if (block.kind === 'text') {
        return <LemonMarkdown>{block.text || '*Add text in component settings.*'}</LemonMarkdown>
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
            {block.title && <h3 className="mb-3">{block.title}</h3>}
            {block.display === 'source' || block.display === 'both' ? (
                <pre className="p-3 rounded bg-surface-secondary overflow-auto text-xs">
                    <code>{source}</code>
                </pre>
            ) : null}
            {block.display !== 'source' && (
                <MarkdownNotebook
                    value={appCellMarkdown(cell)}
                    registry={NOTEBOOK_MARKDOWN_REGISTRY}
                    mode="view"
                    className="NotebookAppBuilder__cell"
                />
            )}
        </div>
    )
}
