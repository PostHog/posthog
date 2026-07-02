import { IconPencil } from '@posthog/icons'

import { DiffFileContent } from './DiffFileContent'
import { FilePath } from './FilePath'
import { GenericMcpToolRenderer } from './GenericMcpToolRenderer'
import { ReadFileContent } from './ReadFileContent'
import { ToolActivity } from './ToolActivity'
import { findAllDiffContent, getDiffStats } from './toolDiffContent'
import type { ToolRendererProps } from './toolRegistry'

/** +added / -removed mono stat chip for a diff. */
function DiffStats({ added, removed }: { added: number; removed: number }): JSX.Element {
    return (
        <span className="font-mono text-xs shrink-0">
            <span className="text-success">+{added}</span> <span className="text-danger">-{removed}</span>
        </span>
    )
}

/**
 * Renderer for Edit / Write / MultiEdit / NotebookEdit. The header reads "Edited a file" / "Created a
 * file" (or "Edited N files"); expanding the card reveals the filename, line stats, and a per-file view:
 * a single-pane read-only editor for a newly created file (no "before" to diff against), an inline visual
 * diff for a real edit. Without `type: "diff"` content blocks it degrades to the generic card.
 */
export function EditDiffRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const diffs = findAllDiffContent(message.content)

    if (diffs.length === 0) {
        return <GenericMcpToolRenderer {...props} />
    }

    const fallbackPath = typeof message.rawInput.file_path === 'string' ? message.rawInput.file_path : undefined
    const isCreate = diffs.length === 1 && diffs[0].oldText == null
    const title = diffs.length > 1 ? `Edited ${diffs.length} files` : isCreate ? 'Created a file' : 'Edited a file'

    const body = (
        <div className="flex flex-col gap-3 w-full min-w-0">
            {diffs.map((diff, index) => {
                const path = diff.path ?? fallbackPath
                const stats = getDiffStats(diff.oldText, diff.newText)
                return (
                    <div key={index} className="flex flex-col gap-1 w-full min-w-0">
                        <div className="flex items-center gap-2 min-w-0">
                            {path && <FilePath path={path} />}
                            <DiffStats added={stats.added} removed={stats.removed} />
                        </div>
                        {diff.oldText == null ? (
                            <ReadFileContent text={diff.newText ?? ''} path={path} />
                        ) : (
                            <DiffFileContent oldText={diff.oldText} newText={diff.newText ?? ''} path={path} />
                        )}
                    </div>
                )
            })}
        </div>
    )

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconPencil />}
            title={title}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
}
