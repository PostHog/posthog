import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconDay, IconLaptop, IconNight } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { SceneExport } from 'scenes/sceneTypes'

import posthogLogo from 'public/posthog-logo.svg'

import { publicStatusPageLogic, PublicStatusPageLogicProps, PublicStatusPageTheme } from './publicStatusPageLogic'
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
    const { page, pageLoading, loadFailed, theme } = useValues(publicStatusPageLogic)
    const { setTheme } = useActions(publicStatusPageLogic)

    useEffect(() => {
        const media = window.matchMedia('(prefers-color-scheme: dark)')
        const apply = (): void => {
            const isDark = theme === 'dark' || (theme === 'system' && media.matches)
            const wanted = isDark ? 'dark' : 'light'
            if (document.body.getAttribute('theme') !== wanted) {
                document.body.setAttribute('theme', wanted)
            }
        }
        apply()
        // App.tsx's useThemedHtml forces unauthenticated scenes to light by setting body[theme]
        // after this effect mounts. Observe the attribute and re-apply our preference whenever it
        // gets reset out from under us.
        const observer = new MutationObserver(apply)
        observer.observe(document.body, { attributes: true, attributeFilter: ['theme'] })
        if (theme === 'system') {
            media.addEventListener('change', apply)
        }
        return () => {
            observer.disconnect()
            media.removeEventListener('change', apply)
        }
    }, [theme])

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
            <div className="max-w-2xl mx-auto mb-4 flex justify-end">
                <LemonSegmentedButton<PublicStatusPageTheme>
                    size="small"
                    value={theme}
                    onChange={setTheme}
                    options={[
                        { value: 'light', icon: <IconDay />, tooltip: 'Light' },
                        { value: 'dark', icon: <IconNight />, tooltip: 'Dark' },
                        { value: 'system', icon: <IconLaptop />, tooltip: 'Sync with system' },
                    ]}
                />
            </div>
            <StatusPagePreview
                title={page.title}
                monitors={page.monitors}
                publishedAt={page.published_at}
                ongoingIncidents={page.ongoing_incidents}
                recentIncidents={page.recent_incidents}
                placeholder="No monitors on this status page yet."
                isPublic
            />
            <footer className="max-w-2xl mx-auto mt-12 flex flex-col items-center gap-2 text-[11px] text-secondary">
                <Link to="https://posthog.com?utm_campaign=in-product&utm_tag=public-status-page-footer">
                    <img src={posthogLogo} alt="PostHog" className="h-4 opacity-70 hover:opacity-100 transition" />
                </Link>
            </footer>
        </div>
    )
}
