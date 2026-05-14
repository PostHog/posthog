import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

import { MOCK_BUILD_SPEC } from '../components/founderMockData'
import { landingLivePreviewLogic, Phase } from '../components/landingLivePreviewLogic'
import { LandingPageMockup } from '../components/LandingPageMockup'
import { founderLogic } from './founderLogic'

const PHASE_LABEL: Record<Phase, string> = {
    loading: 'Loading your project…',
    'no-ideation': 'No ideation yet — finish stage 1 first.',
    'generating-spec': 'Writing your landing-page spec — ~30-60 seconds.',
    'generating-scaffold': 'Rendering the landing page into HTML — under a second.',
    publishing: 'Publishing to GitHub Pages — ~30-60 seconds to provisioning.',
    live: 'Your page is live.',
    error: 'Something went wrong.',
}

export function FounderModeLandingPreview(): JSX.Element {
    const { currentProjectId } = useValues(founderLogic)
    if (!currentProjectId) {
        // No project yet — fall back to the static mock so the scene isn't blank when a
        // visitor lands here before completing stage 1.
        return <PreviewShell projectMissing>{null}</PreviewShell>
    }
    return <PreviewInner projectId={currentProjectId} />
}

function PreviewInner({ projectId }: { projectId: string }): JSX.Element {
    const logic = landingLivePreviewLogic({ projectId })
    const { phase, liveUrl, isWaiting, errorMessage } = useValues(logic)

    return (
        <PreviewShell>
            <LandingPageMockup
                spec={liveUrl ? undefined : MOCK_BUILD_SPEC}
                liveUrl={liveUrl}
                loading={isWaiting && !liveUrl}
                loadingLabel={PHASE_LABEL[phase]}
                footerLabel={
                    phase === 'error' ? `Error: ${errorMessage}` : liveUrl ? `Live at ${liveUrl}` : PHASE_LABEL[phase]
                }
            />
        </PreviewShell>
    )
}

function PreviewShell({
    children,
    projectMissing,
}: {
    children: React.ReactNode
    projectMissing?: boolean
}): JSX.Element {
    return (
        <main className="fixed inset-0 top-[54px] overflow-y-auto bg-bg-3000">
            <div className="max-w-5xl mx-auto p-6 flex flex-col gap-4">
                <header>
                    <h1 className="text-xl font-semibold">Landing page</h1>
                    <p className="text-sm text-text-secondary mt-1">
                        {projectMissing ? (
                            <>
                                No project yet — finish ideation first, then come back here. In the meantime here's the
                                static mockup driven from{' '}
                                <code className="text-xs px-1 py-0.5 rounded bg-fill-highlight-100 border border-border">
                                    MOCK_BUILD_SPEC
                                </code>
                                .
                            </>
                        ) : (
                            <>
                                Auto-generates a landing-page spec, renders it to a single-page static site, and
                                publishes to GitHub Pages — you'll see the live URL embedded below as soon as Pages
                                finishes provisioning. See also{' '}
                                <Link to="/founder/posthog-stack">/founder/posthog-stack</Link> for the PostHog stack
                                recommendations driven from the same spec.
                            </>
                        )}
                    </p>
                </header>
                {projectMissing ? <LandingPageMockup spec={MOCK_BUILD_SPEC} /> : children}
            </div>
        </main>
    )
}

export const scene: SceneExport = {
    component: FounderModeLandingPreview,
}

export default FounderModeLandingPreview
