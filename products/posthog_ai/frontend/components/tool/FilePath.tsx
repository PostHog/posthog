import { IconDocument } from '@posthog/icons'

import { getFilename } from './toolContentUtils'

/**
 * Non-clickable file reference chip — a document icon, the bold filename, and a dimmed parent
 * directory that ellipsizes on overflow. There is no file-open panel in the sandbox UI, so unlike
 * the agent's own FileMentionChip this is purely informational.
 */
export function FilePath({ path }: { path: string }): JSX.Element {
    const filename = getFilename(path)
    const dir = path.slice(0, path.length - filename.length).replace(/\/+$/, '')

    return (
        <span className="inline-flex items-center gap-1 min-w-0 max-w-full font-mono text-xs">
            <IconDocument className="shrink-0 text-muted size-3.5" />
            <span className="font-medium text-secondary shrink-0">{filename}</span>
            {dir && <span className="text-muted truncate">{dir}</span>}
        </span>
    )
}
