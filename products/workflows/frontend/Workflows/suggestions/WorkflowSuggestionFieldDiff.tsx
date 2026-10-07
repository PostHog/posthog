import { Suspense } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import type { MonacoDiffEditorProps } from 'lib/components/MonacoDiffEditor'
import { useBodyIsDark } from 'lib/hooks/useBodyIsDark'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { SuggestedFieldChange, describeFieldView } from './suggestionChanges'

const MonacoDiffEditor = lazyWithRetry(() => import('lib/components/MonacoDiffEditor'))

// Module-level so the editor does not re-apply its options on every render.
const DIFF_OPTIONS: MonacoDiffEditorProps['options'] = {
    automaticLayout: true,
    renderOverviewRuler: false,
    scrollBeyondLastLine: false,
    minimap: { enabled: false },
    wordWrap: 'on',
    diffWordWrap: 'on',
    diffAlgorithm: 'advanced',
    hideUnchangedRegions: {
        enabled: true,
        contextLineCount: 3,
        minimumLineCount: 3,
        revealLineCount: 20,
    },
}

function InlineValue({ value, side }: { value: unknown; side: 'before' | 'after' }): JSX.Element {
    if (value === undefined) {
        return <span className="text-secondary italic">Not set</span>
    }
    if (value === null) {
        return <span className="text-secondary italic">Removed</span>
    }
    return (
        <span
            className={
                side === 'before'
                    ? 'rounded px-1 bg-fill-error-highlight line-through break-all'
                    : 'rounded px-1 bg-fill-success-highlight break-all'
            }
        >
            {typeof value === 'string' ? value : JSON.stringify(value)}
        </span>
    )
}

export function WorkflowSuggestionFieldDiff({ change }: { change: SuggestedFieldChange }): JSX.Element {
    const isDarkModeOn = useBodyIsDark()
    const view = describeFieldView(change)

    const label = (
        <Tooltip title={change.path}>
            <span className="font-medium">{change.label}</span>
        </Tooltip>
    )

    if (view.kind === 'inline') {
        return (
            <div className="flex items-baseline gap-2 flex-wrap">
                {label}
                <InlineValue value={change.before} side="before" />
                <span className="text-secondary">→</span>
                <InlineValue value={change.after} side="after" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-1 w-full">
            <div className="flex items-baseline gap-2">
                {label}
                {change.before === undefined && (
                    <span className="text-xs text-secondary">Added by this suggestion</span>
                )}
                {change.after === null && <span className="text-xs text-secondary">Removed by this suggestion</span>}
            </div>
            {/* Monaco shows an empty side as a changed blank line, so a one-sided change is a plain block. */}
            {view.original === '' || view.modified === '' ? (
                <pre
                    className={`text-xs rounded p-2 mb-0 max-h-80 overflow-auto whitespace-pre-wrap break-words ${
                        view.modified === '' ? 'bg-fill-error-highlight' : 'bg-fill-success-highlight'
                    }`}
                >
                    {view.modified || view.original}
                </pre>
            ) : (
                <div className="border rounded overflow-hidden">
                    <Suspense fallback={<Spinner className="text-2xl mx-auto my-4" />}>
                        <MonacoDiffEditor
                            original={view.original}
                            modified={view.modified}
                            language={view.language}
                            options={DIFF_OPTIONS}
                            theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                        />
                    </Suspense>
                </div>
            )}
        </div>
    )
}
