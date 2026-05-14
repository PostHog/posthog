import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { founderLogic } from '../scenes/founderLogic'
import { founderValidationLogic } from './founderValidationLogic'
import { ValidationNextStep } from './ValidationNextStep'
import { ValidationReportView } from './ValidationReportView'
import { ValidationRunningCard } from './ValidationRunningCard'

export function Step2(): JSX.Element {
    const { currentProjectId } = useValues(founderLogic)

    if (!currentProjectId) {
        return (
            <LemonBanner type="info">
                Complete stage 1 first. The validation step reads from the ideation payload of your founder project.
            </LemonBanner>
        )
    }

    return <Step2Inner projectId={currentProjectId} />
}

function Step2Inner({ projectId }: { projectId: string }): JSX.Element {
    const logic = founderValidationLogic({ projectId })
    // Reading `project` directly (not `projectLoading`) so the UI doesn't flicker between
    // skeletons and content every 2s as poll requests fire. Skeletons only on the very first
    // mount before any project has loaded.
    const { project, report, ideation, validation, status, errorMessage, isRunning, isStale } = useValues(logic)
    const { regenerate } = useActions(logic)
    const { advanceStep } = useActions(founderLogic)

    if (!project) {
        return (
            <div className="flex flex-col gap-3">
                <LemonSkeleton className="h-8 w-1/3" />
                <LemonSkeleton className="h-32 w-full" />
                <LemonSkeleton className="h-32 w-full" />
            </div>
        )
    }

    const lastRunAt = validation?.completed_at ?? validation?.failed_at

    return (
        <div className="flex flex-col gap-4">
            <header className="flex items-baseline justify-between gap-3">
                <div>
                    <h2 className="text-xl font-semibold">Validation</h2>
                    <p className="text-sm text-text-secondary mt-1">
                        Validating <span className="font-medium text-text-primary">{project.name}</span>
                        {lastRunAt && <> · last run {formatRelative(lastRunAt)}</>}
                    </p>
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    onClick={() => regenerate()}
                    disabledReason={isRunning ? 'Validation already running' : undefined}
                    type="secondary"
                    size="small"
                >
                    {report ? 'Re-run' : 'Run validation'}
                </LemonButton>
            </header>

            {isStale && !isRunning && (
                <LemonBanner type="warning" action={{ children: 'Re-run', onClick: () => regenerate() }}>
                    This report was generated against an older version of your ideation. Re-run to refresh.
                </LemonBanner>
            )}

            {status === 'failed' && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => regenerate() }}>
                    {humanizeError(errorMessage)}
                </LemonBanner>
            )}

            {isRunning && (
                <ValidationRunningCard startedAt={validation?.started_at} currentPass={validation?.current_pass} />
            )}

            {!report && !isRunning && status !== 'failed' && (
                <LemonBanner type="info">
                    No validation report yet. Hit "Run validation" to kick off a competitor + assumptions analysis.
                    {!ideation && <> Make sure stage 1 (ideation) is filled in first.</>}
                </LemonBanner>
            )}

            {report && <ValidationReportView report={report} />}

            {report && !isRunning && (
                <ValidationNextStep
                    verdict={report.verdict}
                    onRefine={() => advanceStep('ideation')}
                    onContinue={() => advanceStep('gtm')}
                />
            )}
        </div>
    )
}

// Map raw exception strings the LLM / SDK may produce into something a founder can act on.
// Order matters: check the more specific patterns first.
function humanizeError(raw: string): string {
    const msg = raw?.toLowerCase() ?? ''
    if (!msg) {
        return 'Validation failed with an unknown error. Try again.'
    }
    if (msg.includes('empty response')) {
        return "The model returned an empty response. This usually clears up on a retry — hit 'Retry'."
    }
    if (msg.includes('rate limit') || msg.includes('quota') || msg.includes('429')) {
        return 'Hit a rate limit. Wait a minute and retry.'
    }
    if (msg.includes('timeout') || msg.includes('deadline')) {
        return 'The validation timed out. Retry, or refine ideation to make the prompt shorter.'
    }
    if (msg.includes('validation error') || msg.includes('pydantic')) {
        return 'The model returned an unexpected shape. Retry — this is usually a transient model glitch.'
    }
    if (msg.includes('gemini_api_key') || msg.includes('api key')) {
        return 'GEMINI_API_KEY is missing or invalid on the server. Ask an engineer to check the env.'
    }
    return `Validation failed: ${raw}`
}

function formatRelative(iso: string): string {
    const diffMs = Date.now() - new Date(iso).getTime()
    if (diffMs < 0) {
        return 'just now'
    }
    const seconds = Math.floor(diffMs / 1000)
    if (seconds < 60) {
        return 'just now'
    }
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) {
        return `${minutes} min ago`
    }
    const hours = Math.floor(minutes / 60)
    if (hours < 24) {
        return `${hours} hour${hours === 1 ? '' : 's'} ago`
    }
    const days = Math.floor(hours / 24)
    return `${days} day${days === 1 ? '' : 's'} ago`
}
