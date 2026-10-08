import clsx from 'clsx'
import { Suspense } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import type { MonacoDiffEditorProps } from 'lib/components/MonacoDiffEditor'
import { useBodyIsDark } from 'lib/hooks/useBodyIsDark'
import { lazyWithRetry } from 'lib/utils/retryImport'

const MonacoDiffEditor = lazyWithRetry(() => import('lib/components/MonacoDiffEditor'))

const DIFF_OPTIONS: MonacoDiffEditorProps['options'] = {
    readOnly: true,
    renderSideBySide: false,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    lineNumbers: 'off',
    folding: false,
    hideUnchangedRegions: { enabled: true },
    // The editor sizes itself to the diff after first layout. Without this, Monaco keeps its first
    // measured height and cuts off the last lines.
    automaticLayout: true,
    scrollbar: { alwaysConsumeMouseWheel: false },
    // The compare panel treats any difference in the text as a change, so the diff must show whitespace-only edits too.
    ignoreTrimWhitespace: false,
}

export function InstructionsDiff({ before, after }: { before: string; after: string }): JSX.Element {
    const isDarkMode = useBodyIsDark()

    // Monaco reads empty text as one blank line, so a diff against it would show that line as changed.
    // With nothing on one side, the whole text is either added or removed.
    if (!before || !after) {
        return (
            <div className={clsx('rounded border', before ? 'bg-fill-error-highlight' : 'bg-fill-success-highlight')}>
                <div className="px-2 pt-2 text-xs font-semibold">
                    {before ? 'Instructions removed' : 'New instructions'}
                </div>
                <pre className="m-0 p-2 whitespace-pre-wrap break-words font-mono text-xs">{before || after}</pre>
            </div>
        )
    }

    return (
        <div className="overflow-hidden rounded border">
            <Suspense fallback={<LemonSkeleton className="h-24 w-full" />}>
                <MonacoDiffEditor
                    original={before}
                    value={after}
                    modified={after}
                    language="markdown"
                    theme={isDarkMode ? 'vs-dark' : 'vs'}
                    options={DIFF_OPTIONS}
                    loading={<LemonSkeleton className="h-24 w-full" />}
                />
            </Suspense>
        </div>
    )
}
