import { BindLogic, useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { pageReportsLogic } from 'scenes/web-analytics/pageReportsLogic'

import { pageDirectoryLogic } from './pageDirectoryLogic'
import { PageDirectorySummary } from './PageDirectorySummary'
import { PageDirectoryTable } from './PageDirectoryTable'

function PageDirectoryContent(): JSX.Element {
    const { search, pastedUrl, directoryState, driverError, failedMetrics, isPathCleaningEnabled } =
        useValues(pageDirectoryLogic)
    const { setSearch, loadDriver, retryFailedMetrics } = useActions(pageDirectoryLogic)
    const { openPageReport } = useActions(pageReportsLogic)

    return (
        <div className="flex flex-col gap-3 mt-2 pb-24" data-attr="page-reports-directory">
            <div className="flex flex-col gap-1 min-w-0">
                <h2 className="m-0">Pages</h2>
                <p className="m-0 text-secondary">
                    How each page earns its traffic, from search engines through to AI assistants. Open a page to see
                    its full report.
                </p>
            </div>
            <PageDirectorySummary />
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    className="flex-1 min-w-60 max-w-160"
                    fullWidth
                    placeholder="Search pages, or paste a URL"
                    value={search}
                    onChange={setSearch}
                    onPressEnter={() => {
                        if (pastedUrl) {
                            openPageReport(pastedUrl, 'pasted_url')
                        }
                    }}
                    data-attr="page-reports-directory-search"
                    autoFocus
                />
                {pastedUrl ? (
                    <LemonButton
                        type="primary"
                        sideIcon={<IconArrowRight />}
                        onClick={() => openPageReport(pastedUrl, 'pasted_url')}
                        className="max-w-full"
                        truncate
                        data-attr="page-reports-directory-open-url"
                    >
                        Open report for this URL
                    </LemonButton>
                ) : null}
            </div>
            {directoryState === 'error' ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadDriver(true) }}>
                    Couldn't load your pages. {driverError ? `${driverError}. ` : ''}Try again, or pick a shorter date
                    range.
                </LemonBanner>
            ) : (
                <>
                    {failedMetrics.length > 0 ? (
                        <LemonBanner
                            type="warning"
                            action={{
                                children: 'Try again',
                                onClick: retryFailedMetrics,
                                'data-attr': 'page-reports-directory-retry-metrics',
                            }}
                        >
                            Some columns couldn't load.
                        </LemonBanner>
                    ) : null}
                    <PageDirectoryTable />
                </>
            )}
            <p className="m-0 text-xs text-secondary">
                Images, scripts and other static files are hidden. Path cleaning is{' '}
                <span>{isPathCleaningEnabled ? 'on, so similar paths are grouped' : 'off'}</span>.
            </p>
        </div>
    )
}

export function PageReportsDirectory(): JSX.Element {
    return (
        <BindLogic logic={pageDirectoryLogic} props={{}}>
            <PageDirectoryContent />
        </BindLogic>
    )
}
