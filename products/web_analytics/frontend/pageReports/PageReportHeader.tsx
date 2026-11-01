import { useActions } from 'kea'

import { IconChevronRight, IconEllipsis, IconExternal } from '@posthog/icons'
import { LemonButton, LemonMenu, Link } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { tryDecodeURIComponent } from 'lib/utils/url'
import { urls } from 'scenes/urls'
import { pageReportsLogic } from 'scenes/web-analytics/pageReportsLogic'

import { pageReportDetailLogic } from './pageReportDetailLogic'
import { pageUrlForHost, splitPageKey } from './pageReportsUtils'

export interface PageReportHeaderProps {
    pageKey: string
    pageUrl: string
    selectedHost: string | null
}

export function PageReportHeader({ pageKey, pageUrl, selectedHost }: PageReportHeaderProps): JSX.Element {
    const { backToDirectory } = useActions(pageReportsLogic)
    const { clickOpenPage, clickHeaderMenuItem } = useActions(pageReportDetailLogic)
    const { host, path } = splitPageKey(tryDecodeURIComponent(pageKey))
    const absoluteUrl = pageUrlForHost(pageUrl, selectedHost)
    const canOpen = /^https?:\/\//i.test(absoluteUrl)

    return (
        <div className="flex flex-wrap items-center justify-between gap-2" data-attr="page-report-header">
            <nav aria-label="Breadcrumb" className="flex items-center gap-1 min-w-0 flex-1">
                <Link
                    to={urls.webAnalyticsPageReports()}
                    subtle
                    className="shrink-0"
                    onClick={(event) => {
                        if (!event.shiftKey) {
                            event.preventDefault()
                            backToDirectory()
                        }
                    }}
                    data-attr="page-report-breadcrumb"
                >
                    Page reports
                </Link>
                {host ? (
                    <>
                        <IconChevronRight className="shrink-0 text-secondary" />
                        <span className="shrink-0 text-secondary">{host}</span>
                    </>
                ) : null}
                <IconChevronRight className="shrink-0 text-secondary" />
                <span className="font-semibold text-primary truncate min-w-0" title={path} aria-current="page">
                    {path}
                </span>
            </nav>
            <div className="flex flex-wrap items-center gap-2">
                {canOpen ? (
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={absoluteUrl}
                        targetBlank
                        sideIcon={<IconExternal />}
                        onClick={clickOpenPage}
                        data-attr="page-report-open-page"
                    >
                        Open page
                    </LemonButton>
                ) : null}
                <LemonMenu
                    items={[
                        {
                            label: 'Copy link to this report',
                            onClick: () => {
                                clickHeaderMenuItem('copy_link')
                                void copyToClipboard(window.location.href, 'link to this report')
                            },
                        },
                        ...(canOpen
                            ? [
                                  {
                                      label: 'View heatmap',
                                      to: urls.heatmapNew(
                                          `pageURL=${encodeURIComponent(absoluteUrl)}&dataURL=${encodeURIComponent(absoluteUrl)}`
                                      ),
                                      onClick: () => clickHeaderMenuItem('heatmap'),
                                  },
                              ]
                            : []),
                    ]}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconEllipsis />}
                        aria-label="More actions"
                        data-attr="page-report-more"
                    />
                </LemonMenu>
            </div>
        </div>
    )
}
