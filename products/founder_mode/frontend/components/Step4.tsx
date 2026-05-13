import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { founderLogic } from '../scenes/founderLogic'
import { BuildSpecView } from './BuildSpecView'
import { founderLandingPageLogic } from './founderLandingPageLogic'

export function Step4(): JSX.Element {
    const { currentProjectId } = useValues(founderLogic)

    if (!currentProjectId) {
        return (
            <LemonBanner type="info">
                Complete stage 1 first. The build spec is synthesized from your project's ideation, validation, and GTM.
            </LemonBanner>
        )
    }

    return <Step4Inner projectId={currentProjectId} />
}

function Step4Inner({ projectId }: { projectId: string }): JSX.Element {
    const logic = founderLandingPageLogic({ projectId })
    const { project, spec, status, errorMessage, isRunning } = useValues(logic)
    const { generate } = useActions(logic)

    if (!project) {
        return (
            <div className="flex flex-col gap-3">
                <LemonSkeleton className="h-8 w-1/3" />
                <LemonSkeleton className="h-96 w-full" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <header className="flex items-baseline justify-between gap-3">
                <div>
                    <h2 className="text-xl font-semibold">Launch page build spec</h2>
                    <p className="text-sm text-text-secondary mt-1">
                        A complete build brief for <span className="font-medium text-text-primary">{project.name}</span>{' '}
                        — copy hooks, brand decisions, page sections, PostHog instrumentation. Hand it to a developer or
                        feed it to an AI coding agent to ship the actual Next.js page.
                    </p>
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    onClick={() => generate()}
                    disabledReason={isRunning ? 'Generation already running' : undefined}
                    type="secondary"
                    size="small"
                >
                    {spec ? 'Re-generate' : 'Generate spec'}
                </LemonButton>
            </header>

            {status === 'failed' && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => generate() }}>
                    {humanizeError(errorMessage)}
                </LemonBanner>
            )}

            {isRunning && <RunningCard />}

            {!spec && !isRunning && status !== 'failed' && (
                <LemonBanner type="info">
                    No spec yet. Hit "Generate spec" — usually 15-30 seconds. The spec includes copy, brand decisions,
                    SEO keywords, per-section component recipes, PostHog events, and acceptance criteria.
                </LemonBanner>
            )}

            {spec && <BuildSpecView spec={spec} />}
        </div>
    )
}

function RunningCard(): JSX.Element {
    return (
        <LemonCard className="p-6">
            <div className="flex items-center gap-4">
                <Spinner size="large" />
                <div>
                    <h3 className="text-base font-semibold">Writing your build spec</h3>
                    <p className="text-sm text-text-secondary mt-1">
                        Pulling brief, brand decisions, SEO keywords, per-section copy + design + events, and acceptance
                        criteria. Usually 15-30 seconds.
                    </p>
                </div>
            </div>
        </LemonCard>
    )
}

function humanizeError(raw: string): string {
    const msg = raw?.toLowerCase() ?? ''
    if (!msg) {
        return 'Build spec generation failed. Try again.'
    }
    if (msg.includes('empty response')) {
        return "The model returned an empty response. Hit 'Retry' — usually transient."
    }
    if (msg.includes('rate limit') || msg.includes('quota') || msg.includes('429')) {
        return 'Hit a rate limit. Wait a minute and retry.'
    }
    if (msg.includes('timeout') || msg.includes('deadline')) {
        return 'Generation timed out. Retry, or simplify earlier stages to shorten the prompt.'
    }
    if (msg.includes('validation error') || msg.includes('pydantic')) {
        return 'The model returned an unexpected shape. Retry — usually transient.'
    }
    if (msg.includes('gemini_api_key') || msg.includes('api key')) {
        return 'GEMINI_API_KEY is missing or invalid on the server. Ask an engineer to check the env.'
    }
    return `Build spec generation failed: ${raw}`
}
