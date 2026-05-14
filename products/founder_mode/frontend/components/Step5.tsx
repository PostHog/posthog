import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowLeft, IconCopy, IconDocument, IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { PracticalStepApi, PracticalStepsResultApi, SocialPostApi } from '../generated/api.schemas'
import { founderLogic } from '../scenes/founderLogic'
import { landingLivePreviewLogic } from './landingLivePreviewLogic'
import { LandingPageMockup } from './LandingPageMockup'

const PLATFORM_LABELS: Record<string, string> = {
    product_hunt: 'Product Hunt',
    producthunt: 'Product Hunt',
    linkedin: 'LinkedIn',
    twitter: 'Twitter / X',
    'twitter/x': 'Twitter / X',
    reddit: 'Reddit',
    hacker_news: 'Hacker News',
    hackernews: 'Hacker News',
    indie_hackers: 'Indie Hackers',
}

function platformLabel(raw: string): string {
    return PLATFORM_LABELS[raw.toLowerCase()] ?? raw
}

export function Step5(): JSX.Element {
    const {
        currentProjectId,
        marketingResult,
        marketingStatus,
        marketingIsRunning,
        marketingError,
        marketingLoaded,
        exporting,
    } = useValues(founderLogic)
    const { triggerMarketing, advanceStep, exportToNotebook } = useActions(founderLogic)

    const autoFired = useRef(false)
    useEffect(() => {
        if (marketingLoaded && !autoFired.current && marketingStatus === 'idle' && currentProjectId) {
            autoFired.current = true
            triggerMarketing()
        }
    }, [marketingLoaded, marketingStatus])

    if (!currentProjectId) {
        return (
            <LemonBanner type="info">
                Complete earlier stages first. The marketing plan uses your ideation, validation, GTM, and MVP data.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <header className="flex items-baseline justify-between gap-3">
                <div>
                    <h2 className="text-xl font-semibold">Marketing plan</h2>
                    <p className="text-sm text-text-secondary mt-1">
                        Pre-launch and post-launch actions with ready-to-post content for each channel.
                    </p>
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    onClick={() => triggerMarketing()}
                    disabledReason={marketingIsRunning ? 'Marketing plan already generating' : undefined}
                    type="secondary"
                    size="small"
                >
                    {marketingResult ? 'Re-generate' : 'Generate'}
                </LemonButton>
            </header>

            <LivePagePreview projectId={currentProjectId} />

            {marketingIsRunning && (
                <div className="flex items-center gap-3 p-4 rounded-lg border border-border bg-bg-light">
                    <Spinner className="text-primary" />
                    <span className="text-sm text-text-secondary">
                        Building your launch playbook… this takes ~30-60 seconds
                    </span>
                </div>
            )}

            {marketingStatus === 'failed' && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => triggerMarketing() }}>
                    {marketingError || 'Marketing plan generation failed. Try again.'}
                </LemonBanner>
            )}

            {marketingResult && <MarketingPlanView result={marketingResult} />}

            {marketingResult && !marketingIsRunning && (
                <div className="flex justify-between items-center mt-2 pt-4 border-t border-border">
                    <LemonButton type="secondary" icon={<IconArrowLeft />} onClick={() => advanceStep('mvp')}>
                        Back to MVP
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconDocument />}
                        onClick={() => exportToNotebook()}
                        loading={exporting}
                    >
                        Export all to notebook
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

const PHASE_HINT: Record<string, string> = {
    loading: 'Loading',
    'no-ideation': 'No ideation',
    'generating-spec': 'Writing your landing-page spec',
    'generating-scaffold': 'Rendering the page into HTML',
    publishing: 'Publishing to GitHub Pages',
    live: 'Live',
    error: 'Error',
}

function LivePagePreview({ projectId }: { projectId: string }): JSX.Element {
    // Mounts `landingLivePreviewLogic`, which auto-orchestrates run_landing_page →
    // run_scaffold → publish_scaffold. The mockup component renders three modes:
    // local React mock, a spinner with cycling phrases, and an iframe of the live URL.
    const logic = landingLivePreviewLogic({ projectId })
    const { phase, liveUrl, isWaiting, errorMessage, scaffold } = useValues(logic)
    const repoUrl = scaffold?.repo?.html_url || null

    return (
        <section>
            <h3 className="font-semibold text-base mb-2">Live landing page</h3>
            <LandingPageMockup
                liveUrl={liveUrl}
                loading={isWaiting && !liveUrl}
                loadingLabel={PHASE_HINT[phase]}
                repoUrl={repoUrl}
                footerLabel={
                    phase === 'error' ? `Error: ${errorMessage}` : liveUrl ? `Live at ${liveUrl}` : PHASE_HINT[phase]
                }
            />
        </section>
    )
}

function MarketingPlanView({ result }: { result: PracticalStepsResultApi }): JSX.Element {
    const preLaunch = result.steps.filter(
        (s) => s.timeline.toLowerCase().includes('d-') || s.timeline.toLowerCase().includes('pre')
    )
    const launchDay = result.steps.filter(
        (s) =>
            s.timeline.toLowerCase().includes('launch day') ||
            s.timeline.toLowerCase() === 'd0' ||
            s.timeline.toLowerCase() === 'd-0'
    )
    const postLaunch = result.steps.filter((s) => !preLaunch.includes(s) && !launchDay.includes(s))

    return (
        <div className="flex flex-col gap-6">
            <section className="border border-border rounded-lg p-4">
                <h3 className="font-semibold text-base mb-2">Strategy</h3>
                <p className="text-sm leading-relaxed">{result.launch_summary}</p>
            </section>

            <section className="border border-border rounded-lg p-4">
                <h3 className="font-semibold text-base mb-2">Where to post</h3>
                <div className="flex flex-wrap gap-2">
                    {result.target_communities.map((community, i) => (
                        <span key={i} className="text-xs bg-primary/10 text-primary rounded-full px-3 py-1 font-medium">
                            {community}
                        </span>
                    ))}
                </div>
            </section>

            {preLaunch.length > 0 && <StepGroup title="Pre-launch" steps={preLaunch} />}
            {launchDay.length > 0 && <StepGroup title="Launch day" steps={launchDay} />}
            {postLaunch.length > 0 && <StepGroup title="Post-launch" steps={postLaunch} />}
        </div>
    )
}

function StepGroup({ title, steps }: { title: string; steps: PracticalStepApi[] }): JSX.Element {
    return (
        <section>
            <h3 className="font-semibold text-base mb-3">{title}</h3>
            <div className="flex flex-col gap-3">
                {steps.map((step, i) => (
                    <StepCard key={i} step={step} />
                ))}
            </div>
        </section>
    )
}

function StepCard({ step }: { step: PracticalStepApi }): JSX.Element {
    return (
        <div className="border border-border rounded-lg p-4">
            <div className="flex items-start justify-between gap-3 mb-2">
                <div>
                    <h4 className="font-medium text-sm">{step.title}</h4>
                    <p className="text-xs text-text-secondary mt-0.5">{step.description}</p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                    <span className="text-[10px] uppercase tracking-wide font-semibold bg-primary/10 text-primary rounded px-2 py-0.5">
                        {step.channel}
                    </span>
                    <span className="text-[10px] uppercase tracking-wide text-text-secondary bg-bg-light rounded px-2 py-0.5">
                        {step.timeline}
                    </span>
                </div>
            </div>

            {step.ready_to_use_content.length > 0 && (
                <div className="flex flex-col gap-2 mt-3">
                    {step.ready_to_use_content.map((post, j) => (
                        <PostCard key={j} post={post} />
                    ))}
                </div>
            )}
        </div>
    )
}

function PostCard({ post }: { post: SocialPostApi }): JSX.Element {
    const [copied, setCopied] = useState(false)

    const handleCopy = (): void => {
        void navigator.clipboard.writeText(post.content)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    return (
        <div className="bg-bg-light rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] uppercase tracking-wide font-semibold text-text-secondary">
                    {platformLabel(post.platform)}
                </span>
                <LemonButton size="xsmall" type="secondary" icon={<IconCopy />} onClick={handleCopy}>
                    {copied ? 'Copied!' : 'Copy'}
                </LemonButton>
            </div>
            <p className="text-sm whitespace-pre-wrap font-mono leading-relaxed">{post.content}</p>
            {post.tips && <p className="text-xs text-text-secondary italic mt-2">{post.tips}</p>}
        </div>
    )
}
