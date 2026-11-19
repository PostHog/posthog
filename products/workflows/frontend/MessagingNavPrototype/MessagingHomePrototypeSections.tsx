// PROTOTYPE, never merged: PostHog/michaelr-context#419. What each sidebar row opens. Enough to judge the navigation,
// not the pages themselves: the overview has its own prototype ticket, and the calendar is the shipped send calendar.
import { router } from 'kea-router'
import { useState } from 'react'

import {
    LemonBanner,
    LemonCard,
    LemonSegmentedButton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import type { MessagingSection } from '~/layout/today/messagingNavPrototype/messagingNavPrototypeNav'
import { messagingSectionUrl } from '~/layout/today/messagingNavPrototype/messagingNavPrototypeNav'

import {
    PROTOTYPE_BROADCASTS,
    PROTOTYPE_SENDING_DOMAIN,
    PROTOTYPE_TEMPLATES,
    PROTOTYPE_TRANSACTIONAL,
    PROTOTYPE_WORKFLOWS,
    PrototypeBroadcast,
} from './prototypeData'

function ViewNote({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-xs text-secondary">
            <LemonTag type="muted">Default view</LemonTag>
            <span>{children}</span>
        </div>
    )
}

function Placeholder({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <LemonBanner type="info">
            <div className="font-semibold">{title}</div>
            <div>{children}</div>
        </LemonBanner>
    )
}

function Stat({ label, value, to }: { label: string; value: string; to?: string }): JSX.Element {
    return (
        <LemonCard
            className="flex-1 min-w-40"
            hoverEffect={!!to}
            onClick={to ? () => router.actions.push(to) : undefined}
        >
            <div className="text-xs text-secondary">{label}</div>
            <div className="text-2xl font-semibold">{value}</div>
        </LemonCard>
    )
}

const STATUS_TAG: Record<PrototypeBroadcast['status'], 'default' | 'highlight' | 'success'> = {
    Draft: 'default',
    Scheduled: 'highlight',
    Sent: 'success',
}

function Overview(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <Placeholder title="Place for the overview">
                A later slice fills this page: what went out, what is scheduled, and what needs your attention. Its own
                prototype decides the content.
            </Placeholder>
            <div className="flex flex-wrap gap-3">
                <Stat label="Messages sent, last 7 days" value="4,210" />
                <Stat label="Scheduled this week" value="2" to={messagingSectionUrl('calendar')} />
                <Stat label="Channels to fix" value="1" to={messagingSectionUrl('channels')} />
            </div>
        </div>
    )
}

// The story hands in the shipped send calendar. Importing it here makes the static Storybook build hang on the scene.
let registeredCalendar: (() => JSX.Element) | null = null

export function registerPrototypeCalendar(calendar: () => JSX.Element): void {
    registeredCalendar = calendar
}

function Calendar(): JSX.Element {
    const SendCalendar = registeredCalendar
    return SendCalendar ? (
        <SendCalendar />
    ) : (
        <Placeholder title="Calendar">The shipped send calendar shows here.</Placeholder>
    )
}

function Broadcasts(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <ViewNote>Every broadcast, newest first.</ViewNote>
            <LemonTable
                dataSource={PROTOTYPE_BROADCASTS}
                columns={[
                    { title: 'Name', dataIndex: 'name', render: (_, b) => <Link>{b.name}</Link> },
                    {
                        title: 'Status',
                        dataIndex: 'status',
                        render: (_, b) => <LemonTag type={STATUS_TAG[b.status]}>{b.status}</LemonTag>,
                    },
                    { title: 'Audience', dataIndex: 'audience' },
                    { title: 'Send time', dataIndex: 'when' },
                    {
                        title: 'Recipients',
                        dataIndex: 'recipients',
                        align: 'right',
                        render: (_, b) => (b.recipients === null ? '–' : b.recipients.toLocaleString()),
                    },
                ]}
            />
        </div>
    )
}

function Transactional(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <ViewNote>Every transactional email your code can send, by sends in the last 7 days.</ViewNote>
            <LemonTable
                dataSource={PROTOTYPE_TRANSACTIONAL}
                columns={[
                    { title: 'Name', dataIndex: 'name', render: (_, t) => <Link>{t.name}</Link> },
                    { title: 'ID', dataIndex: 'slug', render: (_, t) => <code className="text-xs">{t.slug}</code> },
                    {
                        title: 'Sent, last 7 days',
                        dataIndex: 'sent7d',
                        align: 'right',
                        render: (_, t) => t.sent7d.toLocaleString(),
                    },
                    { title: 'Last sent', dataIndex: 'lastSent' },
                ]}
            />
        </div>
    )
}

function MessagingWorkflows(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <ViewNote>
                Messaging workflows have an email, SMS or push step. Automations and loops stay in{' '}
                <Link to="/workflows">Workflows</Link>.
            </ViewNote>
            <LemonTable
                dataSource={PROTOTYPE_WORKFLOWS.filter((w) => w.kind === 'Messaging')}
                columns={[
                    { title: 'Name', dataIndex: 'name', render: (_, w) => <Link>{w.name}</Link> },
                    { title: 'Trigger', dataIndex: 'trigger' },
                    {
                        title: 'Channels',
                        dataIndex: 'channels',
                        render: (_, w) => (
                            <div className="flex flex-wrap gap-1">
                                {w.channels.map((c) => (
                                    <LemonTag key={c} type="muted">
                                        {c}
                                    </LemonTag>
                                ))}
                            </div>
                        ),
                    },
                    {
                        title: 'Status',
                        dataIndex: 'status',
                        render: (_, w) => (
                            <LemonTag type={w.status === 'Live' ? 'success' : 'default'}>{w.status}</LemonTag>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function Templates(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="text-xs text-secondary">
                Reusable message content. Workflow templates live in the New workflow chooser.
            </div>
            <LemonTable
                dataSource={PROTOTYPE_TEMPLATES}
                columns={[
                    {
                        title: 'Name',
                        dataIndex: 'name',
                        render: (_, t) => (
                            <span className="flex items-center gap-2">
                                <Link>{t.name}</Link>
                                {t.transactional && <LemonTag type="highlight">Transactional email</LemonTag>}
                            </span>
                        ),
                    },
                    { title: 'Updated', dataIndex: 'updated' },
                ]}
            />
        </div>
    )
}

function Channels(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <LemonBanner type="warning">
                {PROTOTYPE_SENDING_DOMAIN} is missing its DKIM record, so email from it may land in spam.
            </LemonBanner>
            <LemonTable
                dataSource={[
                    { channel: 'Email', setup: PROTOTYPE_SENDING_DOMAIN, state: 'Needs a fix' },
                    { channel: 'SMS', setup: 'Not set up', state: '' },
                    { channel: 'Push', setup: 'Not set up', state: '' },
                    { channel: 'Slack', setup: 'example-workspace', state: 'Connected' },
                ]}
                columns={[
                    { title: 'Channel', dataIndex: 'channel' },
                    { title: 'Setup', dataIndex: 'setup' },
                    {
                        title: 'State',
                        dataIndex: 'state',
                        render: (_, r) =>
                            r.state ? (
                                <LemonTag type={r.state === 'Connected' ? 'success' : 'warning'}>{r.state}</LemonTag>
                            ) : null,
                    },
                ]}
            />
        </div>
    )
}

function Recipients(): JSX.Element {
    const [tab, setTab] = useState<'opt-outs' | 'suppression'>('opt-outs')
    return (
        <div className="flex flex-col gap-3">
            <div className="text-xs text-secondary">Who may receive your messages.</div>
            <LemonSegmentedButton
                size="small"
                value={tab}
                onChange={setTab}
                options={[
                    { value: 'opt-outs', label: 'Opt-outs' },
                    { value: 'suppression', label: 'Suppression list' },
                ]}
            />
            {tab === 'opt-outs' ? (
                <LemonTable
                    dataSource={[
                        { email: 'sam@example.com', topic: 'Product updates', when: '2 days ago' },
                        { email: 'kim@example.com', topic: 'All marketing', when: '1 week ago' },
                    ]}
                    columns={[
                        { title: 'Email', dataIndex: 'email' },
                        { title: 'Topic', dataIndex: 'topic' },
                        { title: 'Opted out', dataIndex: 'when' },
                    ]}
                />
            ) : (
                <LemonTable
                    dataSource={[
                        { email: 'bounce@example.com', reason: 'Hard bounce', when: '3 days ago' },
                        { email: 'old@example.com', reason: 'Complaint', when: '2 weeks ago' },
                    ]}
                    columns={[
                        { title: 'Suppressed address', dataIndex: 'email' },
                        { title: 'Reason', dataIndex: 'reason' },
                        { title: 'Added', dataIndex: 'when' },
                    ]}
                />
            )}
        </div>
    )
}

function Deliverability(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="text-xs text-secondary">Whether mail arrives, and how much PostHog may send.</div>
            <div className="flex flex-wrap gap-3">
                <Stat label="Reputation" value="Good" />
                <Stat label="Daily limit" value="5,000 emails" />
                <Stat label="Frequency cap" value="3 a week" />
            </div>
        </div>
    )
}

function Settings(): JSX.Element {
    const [values, setValues] = useState({ engagement: true, consent: false, utm: true })
    const rows: { key: keyof typeof values; label: string; description: string }[] = [
        { key: 'engagement', label: 'Engagement events', description: 'Capture opens and clicks as events.' },
        { key: 'consent', label: 'Email tracking consent', description: 'Track opens only for people who agreed.' },
        { key: 'utm', label: 'UTM defaults', description: 'Add UTM parameters to links in your messages.' },
    ]
    return (
        <div className="flex max-w-160 flex-col gap-3">
            {rows.map((row) => (
                <LemonCard key={row.key} className="flex items-center justify-between gap-4" hoverEffect={false}>
                    <div>
                        <div className="font-semibold">{row.label}</div>
                        <div className="text-xs text-secondary">{row.description}</div>
                    </div>
                    <LemonSwitch
                        checked={values[row.key]}
                        onChange={(checked) => setValues({ ...values, [row.key]: checked })}
                    />
                </LemonCard>
            ))}
        </div>
    )
}

export const MESSAGING_SECTION_CONTENT: Record<MessagingSection, () => JSX.Element> = {
    overview: Overview,
    calendar: Calendar,
    broadcasts: Broadcasts,
    transactional: Transactional,
    workflows: MessagingWorkflows,
    templates: Templates,
    channels: Channels,
    recipients: Recipients,
    deliverability: Deliverability,
    settings: Settings,
}
