import { IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { MessageTemplate } from '../../../messages/MessageTemplate'
import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import { parseToolOutputRecord } from './extractors'

/** The notebook fields the widget renders, pulled from the REST payload. */
export interface NotebookExtraction {
    shortId: string
    title?: string
    url?: string
}

/**
 * Pulls the rendered fields out of a notebook tool's `rawOutput` — the REST notebook payload
 * (`short_id`, `title`, ProseMirror `content`, …) plus the MCP server's `_posthogUrl` enrichment.
 * The markdown notebook tools return that same short id under `notebook_id` instead, so both
 * spellings are accepted. An output carrying neither isn't a notebook payload and falls back to
 * the generic card.
 */
export function extractNotebook(message: ToolRendererProps['message']): NotebookExtraction | null {
    const output = parseToolOutputRecord(message)
    if (!output) {
        return null
    }

    const { short_id, notebook_id, title, _posthogUrl } = output as {
        short_id?: unknown
        notebook_id?: unknown
        title?: unknown
        _posthogUrl?: unknown
    }
    const shortId = typeof short_id === 'string' ? short_id : typeof notebook_id === 'string' ? notebook_id : null
    if (!shortId) {
        return null
    }

    const inputTitle = message.innerInput?.title
    return {
        shortId,
        title: typeof title === 'string' ? title : typeof inputTitle === 'string' ? inputTitle : undefined,
        url: typeof _posthogUrl === 'string' ? _posthogUrl : undefined,
    }
}

/**
 * Notebook create / update / get tool calls. The tool already persisted the notebook server-side,
 * so v1 is a status line + "Open notebook" CTA — no inline preview, since the REST `content` is a
 * ProseMirror document, not the assistant block format `NotebookArtifactAnswer` renders.
 * Pre-completion or malformed output falls back to the generic card.
 */
export function CreateNotebookWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const notebook = message.status === 'completed' ? extractNotebook(message) : null

    if (!notebook) {
        return <GenericMcpToolRenderer {...props} />
    }

    return (
        <DataToolRow {...props}>
            <MessageTemplate type="ai" wrapperClassName="w-full">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                        <IconNotebook className="text-base" />
                        <span className="font-medium">{notebook.title || 'Notebook ready'}</span>
                    </div>
                    <LemonButton
                        to={notebook.url ?? urls.notebook(notebook.shortId)}
                        targetBlank
                        icon={<IconOpenInNew />}
                        size="xsmall"
                        tooltip="Open notebook"
                    >
                        Open notebook
                    </LemonButton>
                </div>
            </MessageTemplate>
        </DataToolRow>
    )
}
