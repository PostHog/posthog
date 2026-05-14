import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { publicStatusPageLogic, PublicStatusPageLogicProps } from './publicStatusPageLogic'
import { StatusPagePreview } from './StatusPagePreview'

export const scene: SceneExport<PublicStatusPageLogicProps> = {
    component: PublicStatusPageSceneWrapper,
    logic: publicStatusPageLogic,
    paramsToProps: ({ params: { slug } }) => ({ slug }),
}

function PublicStatusPageSceneWrapper(): JSX.Element {
    return <PublicStatusPageScene />
}

function PublicStatusPageScene(): JSX.Element {
    const { page, pageLoading, loadFailed } = useValues(publicStatusPageLogic)

    if (pageLoading && !page) {
        return (
            <div className="min-h-screen flex items-center justify-center">
                <Spinner />
            </div>
        )
    }

    if (loadFailed || !page) {
        return (
            <div className="min-h-screen flex flex-col items-center justify-center gap-2 text-center px-4">
                <div className="text-2xl font-semibold">Status page not found</div>
                <div className="text-sm text-secondary">
                    This page may have been unpublished or the URL may be incorrect.
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-surface-secondary py-12 px-4">
            <StatusPagePreview
                title={page.title}
                monitors={page.monitors}
                publishedAt={page.published_at}
                ongoingIncidents={page.ongoing_incidents}
                recentIncidents={page.recent_incidents}
                placeholder="No monitors on this status page yet."
            />
            <footer className="max-w-2xl mx-auto mt-12 text-center text-[11px] text-secondary">
                Powered by PostHog Uptime
            </footer>
        </div>
    )
}
