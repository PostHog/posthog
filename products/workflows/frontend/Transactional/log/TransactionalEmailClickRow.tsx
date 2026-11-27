import { Link } from '@posthog/lemon-ui'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'

import { EmailOutcomeRow, NO_SESSION_REASON, landingPath, linkLabel, sessionSummary } from './emailClicks'
import { TransactionalEmailEventLink } from './TransactionalEmailEventLink'

export function TransactionalEmailClickRow({ row }: { row: Extract<EmailOutcomeRow, { kind: 'click' }> }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <div className="flex items-baseline gap-2 min-w-0">
                <span className="text-sm font-semibold shrink-0">Clicked</span>
                {row.link ? (
                    <Link to={row.link} target="_blank" className="text-sm truncate" title={row.link}>
                        {linkLabel(row.link)}
                    </Link>
                ) : (
                    <span className="text-sm text-secondary">a link</span>
                )}
                <span className="flex-1" />
                <TransactionalEmailEventLink uuid={row.eventUuid} at={row.at} />
            </div>
            {row.session ? (
                <div className="flex items-center gap-2 min-w-0 rounded border bg-surface-secondary px-2 py-1">
                    <div className="flex flex-col min-w-0">
                        <span className="text-sm truncate" title={row.session.landing_url}>
                            Landed on {landingPath(row.session)}
                        </span>
                        <span className="text-xs text-secondary truncate">{sessionSummary(row.session)}</span>
                    </div>
                    <span className="flex-1" />
                    <ViewRecordingButton
                        sessionId={row.session.session_id}
                        timestamp={row.session.landed_at}
                        checkRecordingExists
                        openPlayerIn={RecordingPlayerType.Modal}
                        size="xsmall"
                        type="secondary"
                        label="Watch from landing"
                        data-attr="transactional-email-outcome-recording"
                    />
                </div>
            ) : (
                row.noSessionReason && (
                    <p className="text-xs text-secondary m-0">{NO_SESSION_REASON[row.noSessionReason]}</p>
                )
            )}
        </div>
    )
}
