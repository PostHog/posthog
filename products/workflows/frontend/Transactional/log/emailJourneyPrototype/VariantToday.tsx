// PROTOTYPE (ticket #385), throwaway. Today's page, drawn from the same invented send with the real components,
// so the variants have something to be compared with.
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type {
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogEventApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { ActivityEvent, buildActivityTimeline, describeComeback } from '../emailActivity'
import { groupActivityRows } from '../emailActivityGroups'
import { TransactionalEmailActivityRail } from '../TransactionalEmailActivityRail'
import { TransactionalEmailDeliveryProgress } from '../TransactionalEmailDeliveryProgress'
import { TransactionalEmailDetails } from '../TransactionalEmailDetails'
import { JourneyEmailPreview } from './JourneyEmailPreview'
import { JourneyData } from './journeyFixtures'

export function asDetail(data: JourneyData): TransactionalEmailLogDetailApi {
    const timeline: TransactionalEmailLogEventApi[] = [
        { kind: 'queued', at: data.queuedAt, reason: null },
        { kind: 'sent', at: data.sentAt, reason: null },
        { kind: 'delivered', at: data.deliveredAt, reason: null },
        ...(data.openedAt ? [{ kind: 'opened' as const, at: data.openedAt, reason: null }] : []),
        ...(data.clicks ?? []).map((click) => ({ kind: 'clicked' as const, at: click.at, reason: null })),
    ]
    return {
        message_id: data.messageId,
        created_at: data.queuedAt,
        status: 'delivered',
        status_at: data.deliveredAt,
        reason: null,
        recipient: data.recipient,
        workflow_id: 'prototype-workflow',
        template_id: 'prototype-template',
        template_name: data.emailName,
        code_email_id: null,
        sending_domain: data.sendingDomain,
        opened: !!data.openedAt,
        clicked: !!data.clicks?.length,
        timeline,
        subject: data.subject,
        distinct_id: data.person?.distinctId ?? '',
        action_id: 'prototype-action',
        sensitive: data.clicks === null,
    }
}

function asEvents(data: JourneyData): ActivityEvent[] {
    const sessions = [
        ...(data.clicks ?? []).flatMap((click) => (click.session ? [click.session] : [])),
        ...data.otherSessions,
    ].filter((session) => session.who === 'recipient')
    return sessions.flatMap((session) =>
        session.events.map((event, index) => ({
            uuid: `${session.id}-${index}`,
            event: event.outcome ? event.label : '$pageview',
            timestamp: event.at,
            url: null,
            pathname: event.label.startsWith('Viewed ') ? event.label.replace('Viewed ', '') : null,
            sessionId: session.recording ? session.id : null,
            eventType: null,
            elementsChain: '',
        }))
    )
}

export function VariantToday({ data }: { data: JourneyData }): JSX.Element {
    const email = asDetail(data)
    const events = asEvents(data)
    const timeline = buildActivityTimeline(events, [], data.sentAt)
    return (
        <div className="@container flex flex-col gap-4">
            <TransactionalEmailDeliveryProgress email={email} />
            <div className="flex flex-col @3xl:flex-row gap-4 items-start">
                <div className="w-full @3xl:flex-1 min-w-0 flex flex-col gap-4 order-last @3xl:order-none">
                    <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                        <div className="flex flex-col gap-0.5">
                            <h3 className="text-base font-semibold m-0">
                                {data.person
                                    ? `What ${data.person.name.split(' ')[0]} did around this email`
                                    : 'Activity around this email'}
                            </h3>
                            <p className="text-xs text-secondary m-0">
                                The person's events in your product before and after this email.
                            </p>
                        </div>
                        {data.person ? (
                            <TransactionalEmailActivityRail
                                before={[]}
                                after={groupActivityRows(timeline.after)}
                                sentAt={data.sentAt}
                                failed={false}
                                sendLabel="Email sent"
                                sendDetail={data.emailName}
                                comeback={describeComeback({ before: [], after: events }, email.timeline)}
                                emptyAfter={events.length ? null : 'No activity in your product since this email.'}
                                hiddenBefore={0}
                                onShowEarlier={() => {}}
                                hiddenAfter={0}
                                onShowLater={() => {}}
                            />
                        ) : (
                            <p className="text-sm text-secondary m-0">
                                This send has no person attached. Pass a <code>distinct_id</code> when you send, and the
                                person's activity before and after the email shows up here.
                            </p>
                        )}
                    </section>
                    <JourneyEmailPreview data={data} />
                </div>
                <div className="w-full @3xl:w-80 shrink-0 flex flex-col gap-4">
                    {data.person && (
                        <section className="border rounded bg-surface-primary p-4 flex flex-col gap-2">
                            <h3 className="text-sm font-semibold m-0">{data.person.name}</h3>
                            <span className="text-xs text-secondary">{data.person.email}</span>
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.personByDistinctId(data.person.distinctId)}
                            >
                                View person
                            </LemonButton>
                        </section>
                    )}
                    <TransactionalEmailDetails email={email} emailUrl={null} />
                </div>
            </div>
        </div>
    )
}
