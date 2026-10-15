import { ReactNode, Suspense, useEffect, useRef, useState } from 'react'

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
                    ? 'rounded px-1 bg-fill-error-highlight line-through break-all whitespace-pre-wrap'
                    : 'rounded px-1 bg-fill-success-highlight break-all whitespace-pre-wrap'
            }
        >
            {typeof value === 'string' ? value : JSON.stringify(value)}
        </span>
    )
}

export function WorkflowSuggestionFieldDiff({
    change,
    action,
}: {
    change: SuggestedFieldChange
    /** Rendered at the end of the field's label row. */
    action?: ReactNode
}): JSX.Element {
    const isDarkModeOn = useBodyIsDark()
    const view = describeFieldView(change)
    const isTwoSidedDiff = view.kind === 'diff' && view.original !== '' && view.modified !== ''
    // Each diff editor costs real main-thread time, and a workflow can hold several long suggestions,
    // so an editor mounts only when its card comes near the screen. The container exists only for a
    // two-sided diff, so the observer attaches again when a field becomes one.
    const diffRef = useRef<HTMLDivElement>(null)
    const [inView, setInView] = useState(false)
    useEffect(() => {
        const element = diffRef.current
        if (inView || !element) {
            return
        }
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    setInView(true)
                    observer.disconnect()
                }
            },
            { rootMargin: '400px' }
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [inView, isTwoSidedDiff])

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
                {action && <div className="ml-auto">{action}</div>}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-1 w-full">
            <div className="flex items-center gap-2 flex-wrap">
                {label}
                {change.before === undefined && (
                    <span className="text-xs text-secondary">Added by this suggestion</span>
                )}
                {change.after === null && <span className="text-xs text-secondary">Removed by this suggestion</span>}
                {action && <div className="ml-auto">{action}</div>}
            </div>
            {/* Monaco shows an empty side as a changed blank line, so a one-sided change is a plain block. */}
            {!isTwoSidedDiff ? (
                <pre
                    className={`text-xs rounded p-2 mb-0 max-h-80 overflow-auto whitespace-pre-wrap break-words ${
                        view.modified === '' ? 'bg-fill-error-highlight' : 'bg-fill-success-highlight'
                    }`}
                >
                    {view.modified || view.original}
                </pre>
            ) : (
                <div ref={diffRef} className="border rounded overflow-hidden">
                    {inView ? (
                        <Suspense fallback={<Spinner className="text-2xl mx-auto my-4" />}>
                            <MonacoDiffEditor
                                original={view.original}
                                modified={view.modified}
                                // The XML tokenizer colors HTML without the HTML language worker, which is not bundled.
                                language={view.language === 'html' ? 'xml' : view.language}
                                options={DIFF_OPTIONS}
                                theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                            />
                        </Suspense>
                    ) : (
                        <Spinner className="text-2xl mx-auto my-4" />
                    )}
                </div>
            )}
        </div>
    )
}
