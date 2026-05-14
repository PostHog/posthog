import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { founderLogic } from './scenes/founderLogic'

export function FounderMode(): JSX.Element {
    const { push } = useActions(router)
    const { hasExistingProject, projectLoaded } = useValues(founderLogic)

    if (projectLoaded && hasExistingProject) {
        push(urls.founderModeLayout())
        return <></>
    }

    return (
        <main className="min-h-screen flex items-center justify-center bg-bg-primary px-6 py-16">
            <div className="w-full max-w-3xl">
                <header className="text-center mb-10">
                    <h1 className="text-3xl font-semibold">Welcome to PostHog</h1>
                    <p className="mt-3 text-text-secondary">Tell us where you're starting from.</p>
                </header>
                <div className="grid gap-6 sm:grid-cols-2">
                    <LemonCard className="p-6" hoverEffect onClick={() => push(urls.onboarding())}>
                        <h2 className="text-lg font-medium">I have a product already</h2>
                        <p className="mt-2 text-sm text-text-secondary">
                            Connect PostHog to an existing app to start capturing events, replays, and more.
                        </p>
                        <span className="mt-6 inline-flex items-center text-sm font-medium">Set up onboarding →</span>
                    </LemonCard>
                    <LemonCard className="p-6" hoverEffect onClick={() => push(urls.founderModeLayout())}>
                        <h2 className="text-lg font-medium">I don't have a product yet</h2>
                        <p className="mt-2 text-sm text-text-secondary">
                            Start in founder mode — we'll help you go from idea to first users.
                        </p>
                        <span className="mt-6 inline-flex items-center text-sm font-medium">Enter founder mode →</span>
                    </LemonCard>
                </div>
            </div>
        </main>
    )
}

export const scene: SceneExport = {
    component: FounderMode,
    logic: founderLogic,
}
