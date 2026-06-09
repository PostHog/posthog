import { memo } from 'react'

import { IconDocument } from '@posthog/icons'

import { getFileName } from '../lib/path'

interface FileMentionChipProps {
    /** Full (relative or absolute) path of the mentioned file. */
    path: string
    /** Optional pre-computed display label; defaults to the path's basename. */
    label?: string
}

/**
 * Read-only file mention chip. Unlike the Electron app's version, this is a
 * static span — there is no editor-open click or context menu, since the
 * transcript renderer is read-only.
 */
export const FileMentionChip = memo(function FileMentionChip({ path, label }: FileMentionChipProps): JSX.Element {
    const filename = getFileName(path)

    // The directory portion shown muted next to the filename, when present.
    const directory = label && label !== filename ? label.replace(`/${filename}`, '') : null

    return (
        <span className="relative top-px inline-flex min-w-0 max-w-full items-center gap-1 align-middle font-mono text-[13px] leading-none">
            <IconDocument className="flex-shrink-0" style={{ fontSize: 12 }} />
            <span className="flex min-w-0 flex-1 items-baseline gap-1 overflow-hidden">
                <span className="flex-shrink-0 whitespace-nowrap font-semibold">{filename}</span>
                {directory && (
                    <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-muted">
                        {directory}
                    </span>
                )}
            </span>
        </span>
    )
})
