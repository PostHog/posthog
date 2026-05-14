import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

import { MOCK_BUILD_SPEC } from '../components/founderMockData'
import { LandingPageMockup } from '../components/LandingPageMockup'

export function FounderModeLandingPreview(): JSX.Element {
    return (
        <main className="fixed inset-0 top-[54px] overflow-y-auto bg-bg-3000">
            <div className="max-w-5xl mx-auto p-6 flex flex-col gap-4">
                <header>
                    <h1 className="text-xl font-semibold">Landing page mockup — preview</h1>
                    <p className="text-sm text-text-secondary mt-1">
                        Visual sandbox for{' '}
                        <code className="text-xs px-1 py-0.5 rounded bg-fill-highlight-100 border border-border">
                            LandingPageMockup
                        </code>{' '}
                        rendered against a hardcoded mock spec. See also{' '}
                        <Link to="/founder/posthog-stack">/founder/posthog-stack</Link> for the PostHog stack
                        recommendations driven from the same spec.
                    </p>
                </header>
                <LandingPageMockup spec={MOCK_BUILD_SPEC} />
            </div>
        </main>
    )
}

export const scene: SceneExport = {
    component: FounderModeLandingPreview,
}

export default FounderModeLandingPreview
