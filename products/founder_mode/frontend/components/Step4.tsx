import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconCopy, IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { MVPHappyPathApi } from '../generated/api.schemas'
import { founderLogic } from '../scenes/founderLogic'

function formatMvpAsText(mvp: MVPHappyPathApi): string {
    const lines: string[] = []

    lines.push('# MVP Spec')
    lines.push('')
    lines.push(mvp.one_liner)
    lines.push('')

    lines.push('## Core flow')
    for (const step of mvp.core_flow) {
        lines.push(`${step.step}. ${step.user_action}`)
        lines.push(`   → ${step.system_response}`)
        lines.push(`   ✓ ${step.success_signal}`)
        lines.push('')
    }

    lines.push('## Must-haves')
    for (const item of mvp.must_haves) {
        lines.push(`- ${item}`)
    }
    lines.push('')

    lines.push('## Deliberately excluded')
    for (const item of mvp.deliberately_excluded) {
        lines.push(`- ${item}`)
    }

    return lines.join('\n')
}

export function Step4(): JSX.Element {
    const { currentProjectId, mvpResult, mvpStatus, mvpIsRunning, mvpError, mvpLoaded } = useValues(founderLogic)
    const { triggerMvp, advanceStep } = useActions(founderLogic)

    const autoFired = useRef(false)
    useEffect(() => {
        if (mvpLoaded && !autoFired.current && mvpStatus === 'idle' && currentProjectId) {
            autoFired.current = true
            triggerMvp()
        }
    }, [mvpLoaded, mvpStatus])

    if (!currentProjectId) {
        return (
            <LemonBanner type="info">
                Complete earlier stages first. The MVP spec is synthesized from your ideation, validation, and GTM.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <header className="flex items-baseline justify-between gap-3">
                <div>
                    <h2 className="text-xl font-semibold">MVP spec</h2>
                    <p className="text-sm text-text-secondary mt-1">
                        Happy-path user journey, must-haves, and anti-bloat list — grounded on everything so far.
                    </p>
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    onClick={() => triggerMvp()}
                    disabledReason={mvpIsRunning ? 'MVP generation already running' : undefined}
                    type="secondary"
                    size="small"
                >
                    {mvpResult ? 'Re-generate' : 'Generate'}
                </LemonButton>
            </header>

            {mvpIsRunning && (
                <div className="flex items-center gap-3 p-4 rounded-lg border border-border bg-bg-light">
                    <Spinner className="text-primary" />
                    <span className="text-sm text-text-secondary">
                        Generating your MVP spec… this takes ~30-60 seconds
                    </span>
                </div>
            )}

            {mvpStatus === 'failed' && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => triggerMvp() }}>
                    {mvpError || 'MVP generation failed. Try again.'}
                </LemonBanner>
            )}

            {mvpResult && <MvpTextBlock mvp={mvpResult} />}

            {mvpResult && !mvpIsRunning && (
                <div className="flex justify-between items-center mt-2 pt-4 border-t border-border">
                    <LemonButton type="secondary" icon={<IconArrowLeft />} onClick={() => advanceStep('gtm')}>
                        Back to GTM
                    </LemonButton>
                    <LemonButton type="primary" sideIcon={<IconArrowRight />} onClick={() => advanceStep('marketing')}>
                        Continue to marketing
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

function MvpTextBlock({ mvp }: { mvp: MVPHappyPathApi }): JSX.Element {
    const [text, setText] = useState(() => formatMvpAsText(mvp))
    const [copied, setCopied] = useState(false)

    useEffect(() => {
        setText(formatMvpAsText(mvp))
    }, [mvp])

    const handleCopy = (): void => {
        void navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    return (
        <div className="relative border border-border rounded-lg">
            <div className="absolute top-2 right-2 z-10">
                <LemonButton type="secondary" size="small" icon={<IconCopy />} onClick={handleCopy}>
                    {copied ? 'Copied!' : 'Copy'}
                </LemonButton>
            </div>
            <textarea
                className="w-full min-h-[400px] p-4 pt-12 text-sm font-mono bg-bg-light rounded-lg border-none resize-y focus:outline-none focus:ring-1 focus:ring-primary"
                value={text}
                onChange={(e) => setText(e.target.value)}
                spellCheck={false}
            />
        </div>
    )
}
