import { IconEllipsis, IconExternal, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'
import { TODAY_REPORT_RECORD_TYPE } from '~/layout/today/todayRecordTypes'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { prFilesUrl } from '../../utils/reportPresentation'
import { QuillDiscussReportButton } from './QuillDiscussReportButton'
import { ReportDetailToolbarProps } from './ReportDetailToolbar'

/**
 * The report page's scene title under the new navigation: the trail back to the inbox, the report's title, and its
 * actions. The trail takes its parent from the inbox's breadcrumbs, so only a `?back=` link passes one.
 */
export function QuillReportDetailHeader({
    report,
    reportUrl,
    name,
    backOverride,
    pullRequest,
    implementAction,
    reportActions,
    evidenceRailCollapsed,
    onToggleEvidenceRail,
}: ReportDetailToolbarProps & { name: string }): JSX.Element {
    return (
        <SceneTitleSection
            name={name}
            nameAction={
                // A report has no file system row, so it pins by its link and shows under Pinned in the Home pane.
                <SidebarPinButton
                    target={{
                        type: TODAY_REPORT_RECORD_TYPE,
                        ref: report.id,
                        name,
                        href: urls.inboxReport('reports', report.id),
                    }}
                    size="icon-sm"
                    dataAttr="inbox-report-title-pin"
                />
            }
            resourceType={{ type: 'inbox' }}
            forceBackTo={backOverride && { key: 'inbox-report-back', ...backOverride }}
            // The detail view scrolls inside its own container, so the title sticks to that container's top edge.
            noPadding
            className="top-0"
            actions={
                <div className="flex flex-wrap items-center justify-end gap-1.5">
                    {pullRequest && (
                        <Button
                            variant="primary"
                            tooltip={`${pullRequest.prRef.repoSlug}#${pullRequest.prRef.number}`}
                            nativeButton={false}
                            render={<LinkPrimitive to={prFilesUrl(pullRequest.prUrl)} target="_blank" />}
                            onClick={() =>
                                captureInboxReportAction({ report, actionType: 'open_pr', surface: 'detail_pane' })
                            }
                        >
                            Open in GitHub
                            <IconExternal />
                        </Button>
                    )}
                    {/* Implement is still a LemonUI component, so it renders outside quill's scoped styles. */}
                    {implementAction && (
                        <span data-not-quill className="contents">
                            {implementAction}
                        </span>
                    )}
                    <QuillDiscussReportButton report={report} reportUrl={reportUrl} />
                    <div className="hidden items-center gap-1.5 @4xl/main-content:flex">
                        {reportActions.map((action) => (
                            <Button
                                key={action.key}
                                variant={action.primary ? 'primary' : 'outline'}
                                loading={action.loading}
                                // A disabled action explains only why it's unavailable, not what it would do.
                                tooltip={action.disabledReason ? undefined : action.tooltip}
                                disabledReason={action.disabledReason}
                                onClick={action.onClick}
                            >
                                {action.icon}
                                {action.label}
                            </Button>
                        ))}
                    </div>
                    {/* A resolved report past its refund window has no secondary actions at all. */}
                    {reportActions.length > 0 && (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        size="icon"
                                        aria-label="More actions"
                                        className="@4xl/main-content:hidden"
                                    />
                                }
                            >
                                <IconEllipsis />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                {reportActions.map((action) => (
                                    <DropdownMenuItem
                                        key={action.key}
                                        disabledReason={action.loading ? 'Working…' : action.disabledReason}
                                        onClick={action.onClick}
                                    >
                                        {action.icon}
                                        {action.label}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                    {evidenceRailCollapsed ? (
                        <Button
                            size="icon"
                            tooltip="Show evidence"
                            aria-label="Show evidence"
                            onClick={onToggleEvidenceRail}
                            data-attr="inbox-report-show-evidence-rail"
                        >
                            <IconSidebarOpen />
                        </Button>
                    ) : (
                        <Button
                            size="icon"
                            tooltip="Hide evidence to widen the report"
                            aria-label="Hide evidence"
                            onClick={onToggleEvidenceRail}
                            data-attr="inbox-report-hide-evidence-rail"
                        >
                            <IconSidebarClose />
                        </Button>
                    )}
                </div>
            }
        />
    )
}
