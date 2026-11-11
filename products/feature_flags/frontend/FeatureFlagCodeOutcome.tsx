import clsx from 'clsx'

import { CodeLine, Language } from 'lib/components/CodeSnippet'

import { OutcomeTone, dedentSnippet, describeOutcome } from './featureFlagCodeSnippets'
import type { FeatureFlagCodeBranchApi } from './generated/api.schemas'

const TONE_HEADER_CLASS: Record<OutcomeTone, string> = {
    off: 'bg-fill-error-highlight',
    on: 'bg-fill-success-highlight',
    neutral: 'bg-surface-secondary',
}

export interface FeatureFlagCodeOutcomeProps {
    branch: FeatureFlagCodeBranchApi
    language: Language
    className?: string
}

export function FeatureFlagCodeOutcome({ branch, language, className }: FeatureFlagCodeOutcomeProps): JSX.Element {
    const outcome = describeOutcome(branch.variant)
    const code = branch.snippet ? dedentSnippet(branch.snippet) : ''
    const lineCount = code.split('\n').length
    // Number the lines only when the snippet spans the range the analysis reported, so a trimmed snippet
    // never shows file line numbers that point at the wrong code.
    const showLineNumbers = code !== '' && lineCount === branch.end_line - branch.start_line + 1

    return (
        <div className={clsx('flex flex-col min-w-0 bg-surface-primary', className)}>
            <div
                className={clsx(
                    'flex flex-wrap items-baseline justify-between gap-x-2 px-3 py-1.5 text-xs border-b',
                    TONE_HEADER_CLASS[outcome.tone]
                )}
            >
                <span className="flex items-baseline gap-1.5 min-w-0">
                    <span className={clsx('font-semibold', outcome.isVariantKey && 'font-mono')}>{outcome.label}</span>
                    <span className="text-secondary">{outcome.caption}</span>
                </span>
                <span className="text-secondary">
                    {branch.start_line === branch.end_line
                        ? `Line ${branch.start_line}`
                        : `Lines ${branch.start_line}-${branch.end_line}`}
                </span>
            </div>
            {code ? (
                <div className="flex overflow-auto max-h-96 font-mono text-xs leading-5 [tab-size:4]">
                    {showLineNumbers && (
                        <pre
                            aria-hidden
                            className="m-0 sticky left-0 py-2 pl-3 pr-2 text-right text-tertiary select-none bg-surface-primary"
                        >
                            {Array.from({ length: lineCount }, (_, index) => branch.start_line + index).join('\n')}
                        </pre>
                    )}
                    <div className={clsx('py-2 pr-3 flex-1', !showLineNumbers && 'pl-3')}>
                        <CodeLine text={code} language={language} wrapLines={false} />
                    </div>
                </div>
            ) : (
                <div className="px-3 py-2 text-secondary text-sm italic">No code runs for this outcome.</div>
            )}
        </div>
    )
}
