import '../detail/QuillReportDetail.scss'
import '../tabs/QuillInboxList.scss'

import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { canResolveReport } from '@posthog/agent-contracts/signal-report-state'
import { IconArrowRight, IconEllipsis } from '@posthog/icons'
import { ProfilePicture } from '@posthog/lemon-ui'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sourceIcon } from 'scenes/project-homepage/today/todayRowIcons'
import { reportSourceLine, reportTitle } from 'scenes/project-homepage/today/todaySignalReports'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { InboxReportSectionKey, SignalReport } from '../../types'
import { isReportClaimable, reportClaimant } from '../../utils/reportClaim'
import { reportOwnerKind } from '../../utils/reportFacts'
import { QuillReportFacts } from '../detail/QuillReportFacts'
import { useReportResolve } from '../detail/useReportResolve'
import { useReportDismiss } from './useReportDismiss'

// A row stacks its icons in a column, so more than 2 would make the row taller than its text.
const MAX_ICONS = 2

interface RowAction {
    key: string
    label: string
    loading?: boolean
    onClick: (event: React.MouseEvent) => void
}

export const QuillReportRow = memo(function QuillReportRow({
    report,
    sectionKey,
    timestampField,
}: {
    report: SignalReport
    sectionKey: InboxReportSectionKey
    timestampField: 'created_at' | 'updated_at'
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const listLogic = reportListLogic(sectionListLogicProps(sectionKey))
    const { claimSavingReportIds } = useValues(listLogic)
    const { dismissReport, removeReport, setReportClaimed } = useActions(listLogic)
    const title = reportTitle(report)
    const myUuid = user?.uuid ?? null
    const claimant = reportClaimant(report)
    const ownerKind = reportOwnerKind(report, myUuid)
    const open = sectionKey === 'needs-decision' || sectionKey === 'monitoring'
    const sources = reportSourceLine(report)
    const icons = [...new Set(report.source_products?.length ? report.source_products : [undefined])]
        .slice(0, MAX_ICONS)
        .map(sourceIcon)

    const { isDismissing, onDismissClick } = useReportDismiss({
        reportId: report.id,
        cardTitle: title,
        report,
        surface: 'list_row',
        onDismiss: (dismissal) => dismissReport(report.id, dismissal),
    })
    const { isResolving, onResolveClick } = useReportResolve({
        report,
        surface: 'list_row',
        onResolved: () => removeReport(report.id),
    })

    const actions: RowAction[] = open
        ? [
              ...(isReportClaimable(report, myUuid)
                  ? [
                        {
                            key: 'claim',
                            label: 'Claim',
                            loading: claimSavingReportIds.includes(report.id),
                            onClick: () => setReportClaimed(report, true, 'list_row'),
                        },
                    ]
                  : canResolveReport(report)
                    ? [{ key: 'resolve', label: 'Resolve', loading: isResolving, onClick: onResolveClick }]
                    : []),
              { key: 'dismiss', label: 'Dismiss', loading: isDismissing, onClick: onDismissClick },
          ]
        : []

    return (
        <li className="QuillReportRow group/report" data-attr="inbox-report-row">
            <span className="QuillReportRow__icons" title={sources.title || sources.line}>
                {icons.map((icon, index) => (
                    // eslint-disable-next-line react/forbid-dom-props
                    <span key={index} className="QuillReportRow__icon" style={{ color: icon.color }}>
                        {icon.glyph}
                    </span>
                ))}
            </span>
            <LinkPrimitive
                to={urls.inboxReport('reports', report.id)}
                className="QuillReportRow__link"
                data-attr="inbox-report-row-link"
            >
                <span className="QuillReportRow__title">{title}</span>
                <QuillReportFacts
                    report={report}
                    timestampField={timestampField}
                    className="mt-0.5 flex flex-wrap items-center gap-x-1.5"
                />
            </LinkPrimitive>
            <div className="QuillReportRow__end">
                {!phoneLayout && (
                    <span className="QuillReportRow__actions">
                        {actions.map((action) => (
                            <Button
                                key={action.key}
                                size="sm"
                                variant="link-muted"
                                loading={action.loading}
                                onClick={action.onClick}
                                data-attr={`inbox-report-row-${action.key}`}
                            >
                                {action.label}
                            </Button>
                        ))}
                    </span>
                )}
                {claimant && (
                    <span className={ownerKind.endsWith('agent') ? 'QuillReportOwner__agent' : undefined}>
                        <ProfilePicture user={claimant} size="sm" />
                    </span>
                )}
                {phoneLayout && actions.length > 0 ? (
                    // A phone has no hover, so the same actions sit behind a menu that is always there.
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-sm"
                                    variant="link-muted"
                                    aria-label="More actions"
                                    data-attr="inbox-report-row-more"
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {actions.map((action) => (
                                <DropdownMenuItem
                                    key={action.key}
                                    disabledReason={action.loading ? 'Working…' : undefined}
                                    onClick={action.onClick}
                                    data-attr={`inbox-report-row-${action.key}`}
                                >
                                    {action.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                ) : (
                    <IconArrowRight className="QuillReportRow__arrow" aria-hidden />
                )}
            </div>
        </li>
    )
})
