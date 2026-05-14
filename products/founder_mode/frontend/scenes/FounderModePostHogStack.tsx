import { SceneExport } from 'scenes/sceneTypes'

import { MOCK_BUILD_SPEC } from '../components/founderMockData'
import { PostHogStackView } from '../components/PostHogStackView'

export function FounderModePostHogStack(): JSX.Element {
    return (
        <main className="fixed inset-0 top-[54px] overflow-y-auto bg-bg-3000">
            <div className="max-w-4xl mx-auto p-6 flex flex-col gap-4">
                <header>
                    <h1 className="text-xl font-semibold">Your PostHog stack</h1>
                    <p className="text-sm text-text-secondary mt-1">
                        These are the PostHog products to set up for{' '}
                        <span className="font-medium text-text-primary">{MOCK_BUILD_SPEC.project_name}</span>, in the
                        order they earn their keep. Recommendations are derived from your build spec — events you plan
                        to capture, pains that still lack evidence, and sections you flagged as optional.
                    </p>
                </header>
                <PostHogStackView spec={MOCK_BUILD_SPEC} />
            </div>
        </main>
    )
}

export const scene: SceneExport = {
    component: FounderModePostHogStack,
}

export default FounderModePostHogStack
