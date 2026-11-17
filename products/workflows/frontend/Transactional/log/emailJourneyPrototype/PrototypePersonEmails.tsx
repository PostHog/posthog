// PROTOTYPE (ticket #385), throwaway. The person's Emails tab as an entry point: each row says what the email led to
// and opens the send detail page, instead of a content-only modal.
import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { journeyData, sessionsFromClicks } from './journeyFixtures'
import { JourneyPrototypeSwitcher } from './JourneyPrototypeSwitcher'
import { useEmailJourneyPrototype } from './useEmailJourneyPrototype'

interface Row {
    id: string
    subject: string
    source: string
    sentAt: string
    opened: boolean
    clicks: number | null
    sessions: number
}

export function PrototypePersonEmails(): JSX.Element {
    const prototype = useEmailJourneyPrototype()
    const data = journeyData(prototype.journeyCase)
    const rows: Row[] = [
        {
            id: data.messageId,
            subject: data.subject,
            source: 'Transactional: Trial ending',
            sentAt: data.sentAt,
            opened: !!data.openedAt,
            clicks: data.clicks?.length ?? null,
            sessions: sessionsFromClicks(data),
        },
        {
            id: 'prototype-welcome',
            subject: 'Welcome to Hedgebox',
            source: 'Workflow: Onboarding',
            sentAt: '2026-11-03T10:15:00Z',
            opened: true,
            clicks: 1,
            sessions: 1,
        },
        {
            id: 'prototype-receipt',
            subject: 'Your receipt',
            source: 'Broadcast: November update',
            sentAt: '2026-11-01T09:00:00Z',
            opened: false,
            clicks: 0,
            sessions: 0,
        },
    ]
    return (
        <>
            <LemonTable
                dataSource={rows}
                rowKey="id"
                columns={[
                    {
                        title: 'Subject',
                        key: 'subject',
                        render: (_, row) => (
                            <Link
                                to={prototype.withParams(urls.transactionalEmailLogEntry(data.messageId))}
                                className="font-semibold"
                            >
                                {row.subject}
                            </Link>
                        ),
                    },
                    {
                        title: 'From',
                        key: 'source',
                        render: (_, row) => <span className="text-secondary">{row.source}</span>,
                    },
                    {
                        title: 'Sent',
                        key: 'sent',
                        render: (_, row) => <TZLabel time={row.sentAt} formatDate="MMM D" formatTime="HH:mm" />,
                    },
                    {
                        title: 'What it led to',
                        key: 'led',
                        render: (_, row) =>
                            row.clicks === null ? (
                                <span className="text-secondary text-xs">Clicks not tracked</span>
                            ) : row.sessions ? (
                                <LemonTag type="success">{pluralize(row.sessions, 'session')} from a click</LemonTag>
                            ) : row.clicks ? (
                                <LemonTag type="muted">{pluralize(row.clicks, 'click')}</LemonTag>
                            ) : (
                                <span className="text-secondary text-xs">{row.opened ? 'Opened' : 'Not opened'}</span>
                            ),
                    },
                ]}
            />
            <JourneyPrototypeSwitcher />
        </>
    )
}
