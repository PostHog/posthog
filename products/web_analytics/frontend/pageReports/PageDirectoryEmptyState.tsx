import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { pageDirectoryLogic } from './pageDirectoryLogic'

export function PageDirectoryEmptyState(): JSX.Element | null {
    const { directoryState, search } = useValues(pageDirectoryLogic)

    if (directoryState === 'no-matches') {
        return (
            <p className="text-secondary m-0 py-6 text-center">
                No pages match "{search.trim()}" in this date range. Try a shorter search, or paste a full URL to open
                its report.
            </p>
        )
    }
    if (directoryState === 'no-traffic') {
        return (
            <p className="text-secondary m-0 py-6 text-center">
                No pageviews in this date range. Pick a longer date range to see your pages.
            </p>
        )
    }
    if (directoryState === 'no-events') {
        return (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
                <p className="text-secondary m-0">No pageviews yet. Pages appear here once your site sends events.</p>
                <LemonButton type="secondary" size="small" to={urls.webAnalyticsHealth()}>
                    Check your installation
                </LemonButton>
            </div>
        )
    }
    return null
}
