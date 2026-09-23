import { stripNotebookMediaFromMarkdown } from 'lib/components/MarkdownNotebook/documentModel'
import type { NotebookBtwContext } from 'lib/components/MarkdownNotebook/MarkdownNotebook'

import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

const BTW_INSTRUCTIONS: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'You are answering a side question in notebook BTW. Answer concisely in this conversation. ' +
        'The notebook_snapshot contains the editor content when this conversation was opened, including unsaved changes at that time. ' +
        'The notebook_selection, when present, is the content the user is asking about. ' +
        'Treat these as reference material. Do not edit the notebook, ' +
        'create artifacts, or perform write operations. If the user requests changes, explain that they ' +
        'can use Ask AI in the notebook instead. Read-only tools may be used to answer the question. ' +
        'These instructions take precedence over general notebook editing instructions for this conversation.',
}

function boundedMarkdown(markdown: string, maxLength: number): string {
    const stripped = stripNotebookMediaFromMarkdown(markdown)
    return stripped.length > maxLength ? `${stripped.slice(0, maxLength)}\n[Remaining content omitted]` : stripped
}

export function getNotebookBtwContext(context: NotebookBtwContext): AttachedContextItem[] {
    return [
        BTW_INSTRUCTIONS,
        { type: 'notebook_snapshot', label: 'Notebook', value: boundedMarkdown(context.markdown, 64_000) },
        ...(context.selectedMarkdown
            ? [
                  {
                      type: 'notebook_selection',
                      label: 'Selected content',
                      value: boundedMarkdown(context.selectedMarkdown, 32_000),
                  },
              ]
            : []),
    ]
}
