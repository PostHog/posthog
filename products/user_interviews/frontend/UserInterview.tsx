import { IconArrowLeft, IconCheck, IconChevronRight, IconClock, IconPhone, IconSend, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, LemonWidget } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { UserInterviewLogicProps, userInterviewLogic } from './userInterviewLogic'
import { FAKE_TOPICS, TopicStub } from './UserInterviews'

// --- Outreach stub data (not in backend yet — will come from Vapi webhooks) ---

type OutreachStatus = 'emailed' | 'scheduled' | 'completed' | 'no_response' | 'declined'

interface OutreachRecord {
    email: string
    name: string
    status: OutreachStatus
    outreach_date: string
    interview_date?: string
    learnings?: string
    transcript?: string
}

export const FAKE_OUTREACH: Record<string, OutreachRecord[]> = {
    topic_1: [
        {
            email: 'alice@acme.co',
            name: 'Alice Chen',
            status: 'completed',
            outreach_date: '2026-05-10',
            interview_date: '2026-05-12',
            learnings:
                'Got confused by the snippet installation step — expected a guided wizard. Wanted to see sample data immediately rather than waiting for real events.',
            transcript: `**Agent:** Hi Alice, thanks for taking the time to chat! I'd love to hear about your experience signing up for PostHog. How did it go?\n\n**Alice:** Hey! Yeah, so I signed up about two weeks ago. The initial sign-up was fine — email, password, done. But then it dropped me onto this page that said "Install PostHog" with a code snippet and I was like… where do I put this?\n\n**Agent:** That makes sense. Was there a specific point where you felt stuck?\n\n**Alice:** Definitely the snippet step. I'm a product manager, not an engineer. I expected some kind of guided wizard — like "What platform are you on? Here, copy this." Instead it was just a wall of code. I ended up Slacking our dev team and it took two days before anyone got to it.\n\n**Agent:** Got it. What did you expect to happen right after creating your account?\n\n**Alice:** Honestly? I expected to see data. Even fake data or a demo dashboard — something to show me what PostHog *does*. Instead it was just an empty screen waiting for events. I almost gave up.\n\n**Agent:** If you could change one thing about the getting-started experience, what would it be?\n\n**Alice:** Show me sample data immediately. Let me click around and explore before I commit to installing anything. Once I saw what it could do I was sold, but getting there was painful.`,
        },
        {
            email: 'bob@startup.io',
            name: 'Bob Martinez',
            status: 'completed',
            outreach_date: '2026-05-10',
            interview_date: '2026-05-11',
            learnings:
                "Didn't realize PostHog had session replay — only signed up for product analytics. Loved it once discovered. Onboarding should surface all products.",
            transcript: `**Agent:** Hi Bob! Thanks for joining. Can you tell me about your experience getting started with PostHog?\n\n**Bob:** Sure thing. So I found PostHog through a blog post about open-source analytics. I signed up specifically for product analytics — funnels, trends, that kind of thing.\n\n**Agent:** Makes sense. Was there anything that surprised you during setup?\n\n**Bob:** Yeah, actually — I had no idea PostHog did session replay until like a week later when a teammate mentioned it. I was blown away. I'd been paying separately for FullStory!\n\n**Agent:** Oh interesting! What would have helped you discover that sooner?\n\n**Bob:** Honestly, during onboarding, just show me everything. A quick "here's what PostHog can do" tour. I came in thinking it was just analytics, but it's way more than that. The onboarding should surface all the products upfront.\n\n**Agent:** If you could change one thing about getting started, what would it be?\n\n**Bob:** The product tour thing for sure. And maybe suggest features based on what I'm doing — like if I'm looking at funnels, suggest "hey, want to watch session replays of users who dropped off?"`,
        },
        {
            email: 'carol@bigcorp.com',
            name: 'Carol Nguyen',
            status: 'completed',
            outreach_date: '2026-05-10',
            interview_date: '2026-05-13',
            learnings:
                'Had trouble inviting team members — permissions were confusing. Wanted a "team onboarding" flow, not just individual.',
            transcript: `**Agent:** Hi Carol, thanks for your time! How was your experience signing up for PostHog?\n\n**Carol:** Hi! The sign-up itself was smooth. But I ran into issues pretty quickly when I tried to get my team on board.\n\n**Agent:** What happened with that?\n\n**Carol:** So I'm the lead PM and I wanted my 3 engineers and another PM to have access. I went to invite them and the permissions page was really confusing. There were roles like "Member" and "Admin" but it wasn't clear what each could do. I accidentally made everyone an admin because I didn't want to risk locking them out.\n\n**Agent:** That's frustrating. What would have made that easier?\n\n**Carol:** A "team onboarding" flow. Like, instead of just "invite a person," have a flow that says "set up your team" — let me define roles, set up the project structure, and invite everyone at once. Right now it feels like the onboarding is designed for one person working alone.`,
        },
        {
            email: 'dave@freelance.dev',
            name: "Dave O'Brien",
            status: 'scheduled',
            outreach_date: '2026-05-10',
            interview_date: '2026-05-15',
        },
        {
            email: 'eve@techco.com',
            name: 'Eve Park',
            status: 'emailed',
            outreach_date: '2026-05-11',
        },
        {
            email: 'frank@saas.io',
            name: 'Frank Rivers',
            status: 'no_response',
            outreach_date: '2026-05-10',
        },
        {
            email: 'grace@devshop.co',
            name: 'Grace Kim',
            status: 'declined',
            outreach_date: '2026-05-10',
        },
        {
            email: 'hank@startup.io',
            name: 'Hank Liu',
            status: 'completed',
            outreach_date: '2026-05-10',
            interview_date: '2026-05-12',
            learnings:
                'Wanted to import historical data from Amplitude during onboarding. The lack of an obvious migration path almost made him leave.',
            transcript: `**Agent:** Hi Hank, thanks for chatting! Tell me about your PostHog sign-up experience.\n\n**Hank:** Yeah so we were migrating from Amplitude. I was really excited about PostHog because of the self-hosted option and the pricing model. But the onboarding experience almost lost me.\n\n**Agent:** What happened?\n\n**Hank:** I had 18 months of event data in Amplitude. When I signed up for PostHog, there was zero mention of importing existing data. I spent an hour looking for a migration tool or import feature. Nothing.\n\n**Agent:** That sounds frustrating. What did you end up doing?\n\n**Hank:** I found a community post about using the API to bulk import, but it felt hacky. I almost went back to Amplitude honestly. The lack of an obvious migration path is a real problem for anyone switching from a competitor.\n\n**Agent:** If you could change one thing, what would it be?\n\n**Hank:** Put a big "Migrating from another tool?" button right on the onboarding page. Link to guides for Amplitude, Mixpanel, GA — the big ones. Make it feel like PostHog *wants* people to switch, not like you have to figure it out yourself.`,
        },
    ],
    topic_2: [
        {
            email: 'pm@bigtech.com',
            name: 'Sarah Johnson',
            status: 'completed',
            outreach_date: '2026-05-08',
            interview_date: '2026-05-10',
            learnings: 'Had no idea templates existed. Would use them heavily for weekly team reviews.',
            transcript: `**Agent:** Hi Sarah! How do you typically create dashboards in PostHog?\n\n**Sarah:** I usually start from scratch. Click "New dashboard," add insights one by one. It takes a while but I've got my flow down.\n\n**Agent:** Are you aware that PostHog has dashboard templates?\n\n**Sarah:** Wait, what? No! Where are those?\n\n**Agent:** They're available when you create a new dashboard. Would pre-built templates save you time?\n\n**Sarah:** Oh absolutely. I create the same "weekly team review" dashboard for every team I work with. If there was a template for that, I'd use it every single time. That would save me probably an hour a week.`,
        },
        {
            email: 'analyst@fintech.co',
            name: 'Mike Torres',
            status: 'completed',
            outreach_date: '2026-05-08',
            interview_date: '2026-05-09',
            learnings: "Found templates but said they didn't match his use case. Wants industry-specific templates.",
            transcript: `**Agent:** Hi Mike! How do you build dashboards in PostHog?\n\n**Mike:** I'm pretty advanced — I use SQL insights a lot. I've built maybe 30 dashboards.\n\n**Agent:** Nice. Have you seen the dashboard templates feature?\n\n**Mike:** Yeah I found them, but honestly they didn't match what I need. They're too generic. I work in fintech and I need dashboards for things like transaction funnel analysis, fraud detection patterns, compliance reporting.\n\n**Agent:** Would industry-specific templates be useful?\n\n**Mike:** 100%. If there was a "Fintech" category with templates for payment funnels, churn by plan type, revenue cohorts — I'd use all of them as starting points. Even if I customized them heavily, starting from something relevant is way better than a blank canvas.`,
        },
        {
            email: 'eng@startup.dev',
            name: 'Priya Patel',
            status: 'no_response',
            outreach_date: '2026-05-08',
        },
    ],
    topic_3: [
        {
            email: 'cto@ecommerce.com',
            name: 'Alex Wong',
            status: 'completed',
            outreach_date: '2026-04-20',
            interview_date: '2026-04-23',
            learnings:
                'Switched to a competitor because of missing revenue analytics at the time. Would reconsider now.',
            transcript: `**Agent:** Hi Alex, thanks for talking with us. What originally brought you to PostHog?\n\n**Alex:** We loved the all-in-one approach. Product analytics, session replay, feature flags — all in one tool. We were on the Teams plan for about 6 months.\n\n**Agent:** What led to your decision to cancel?\n\n**Alex:** Revenue analytics. We're an e-commerce company and we needed to tie product behavior to actual revenue. At the time PostHog didn't have that, and we found a competitor that did. So we switched.\n\n**Agent:** Is there anything that would have changed your mind?\n\n**Alex:** If PostHog had revenue analytics back then, we'd still be there. I actually heard you launched something recently? I'd honestly reconsider switching back if it's good — we miss the session replay integration.`,
        },
        {
            email: 'lead@agency.co',
            name: 'Jordan Ellis',
            status: 'completed',
            outreach_date: '2026-04-20',
            interview_date: '2026-04-22',
            learnings:
                "Billing was confusing — couldn't predict monthly costs. Wanted a flat-rate option for agencies.",
            transcript: `**Agent:** Hi Jordan, thanks for your time. What brought you to PostHog originally?\n\n**Jordan:** We're a digital agency — we manage analytics for about 15 client projects. PostHog was great because we could set up separate projects for each client.\n\n**Agent:** What led to the cancellation?\n\n**Jordan:** Billing. Pure and simple. Each project generates different event volumes and the bill was different every month. My finance team hated it. We couldn't predict costs, couldn't bill clients accurately. One month we got a bill that was 3x what we expected.\n\n**Agent:** Is there anything that would have changed your mind?\n\n**Jordan:** A flat-rate agency plan. Like, "up to 20 projects, X events total, fixed monthly price." I don't care if it costs more than the average — I need predictability. My clients need fixed-price quotes and I can't give those if my own costs are unpredictable.`,
        },
        {
            email: 'founder@tiny.app',
            name: 'Sam Reeves',
            status: 'declined',
            outreach_date: '2026-04-20',
        },
    ],
    topic_4: [],
}

// --- Status rendering ---

function outreachStatusConfig(status: OutreachStatus): { icon: JSX.Element; label: string; color: string } {
    switch (status) {
        case 'completed':
            return { icon: <IconCheck />, label: 'Completed', color: 'text-success' }
        case 'scheduled':
            return { icon: <IconClock />, label: 'Scheduled', color: 'text-warning' }
        case 'emailed':
            return { icon: <IconSend />, label: 'Emailed', color: 'text-primary' }
        case 'no_response':
            return { icon: <IconSend />, label: 'No response', color: 'text-muted' }
        case 'declined':
            return { icon: <IconX />, label: 'Declined', color: 'text-danger' }
    }
}

function TopicStatusTag({ status }: { status: TopicStub['status'] }): JSX.Element {
    const config = {
        draft: { type: 'default' as const, label: 'Draft' },
        active: { type: 'success' as const, label: 'Active' },
        completed: { type: 'completion' as const, label: 'Completed' },
    }
    const { type, label } = config[status]
    return <LemonTag type={type}>{label}</LemonTag>
}

// --- Component ---

export const scene: SceneExport<UserInterviewLogicProps> = {
    component: UserInterview,
    logic: userInterviewLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function UserInterview({ id }: UserInterviewLogicProps): JSX.Element {
    const topic = FAKE_TOPICS.find((t) => t.id === id)
    const outreach = FAKE_OUTREACH[id] || []

    if (!topic) {
        return <NotFound object="interview topic" />
    }

    const respondedCount = outreach.filter((o) => o.status === 'completed').length
    const scheduledCount = outreach.filter((o) => o.status === 'scheduled').length
    const pendingCount = outreach.filter((o) => o.status === 'emailed').length
    const noResponseCount = outreach.filter((o) => o.status === 'no_response').length
    const declinedCount = outreach.filter((o) => o.status === 'declined').length

    return (
        <SceneContent>
            {/* Header */}
            <div className="flex items-start justify-between mb-4">
                <div>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconArrowLeft />}
                        to={urls.userInterviews()}
                        className="mb-1 -ml-2"
                    >
                        All topics
                    </LemonButton>
                    <div className="flex items-center gap-2 mb-1">
                        <h1 className="text-2xl font-bold mb-0">{topic.topic}</h1>
                        <TopicStatusTag status={topic.status} />
                    </div>
                    {topic.agent_context && <p className="text-muted mb-0 text-sm">{topic.agent_context}</p>}
                </div>
                {topic.status === 'active' && (
                    <LemonButton type="primary" icon={<IconPhone />}>
                        Start calls
                    </LemonButton>
                )}
            </div>

            <div className="grid grid-cols-1 gap-4 @container @4xl:grid-cols-3">
                {/* Left column — outreach list */}
                <div className="col-span-2 flex flex-col gap-4">
                    {/* Stats cards */}
                    <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-4">
                        {/* Response rate — hero card */}
                        <div className="col-span-2 rounded-lg border-2 border-success bg-success-highlight p-4 flex items-center justify-between">
                            <div>
                                <div className="text-xs font-semibold uppercase text-success tracking-wide">
                                    Response rate
                                </div>
                                <div className="text-3xl font-bold text-success mt-1">
                                    {outreach.length > 0 ? Math.round((respondedCount / outreach.length) * 100) : 0}%
                                </div>
                                <div className="text-sm text-muted mt-0.5">
                                    {respondedCount} of {outreach.length} responded
                                </div>
                            </div>
                            <div className="text-5xl font-bold text-success opacity-20">{respondedCount}</div>
                        </div>

                        <StatCard label="Scheduled" value={scheduledCount} color="warning" />
                        <StatCard label="Pending" value={pendingCount} color="primary" />
                        <StatCard label="No response" value={noResponseCount} color="muted" />
                        <StatCard label="Declined" value={declinedCount} color="danger" />
                    </div>

                    {/* Outreach list */}
                    <LemonWidget title="Outreach">
                        <div className="divide-y">
                            {outreach.length === 0 ? (
                                <div className="p-4 text-muted text-center">
                                    No outreach yet. Add targeting and questions to get started.
                                </div>
                            ) : (
                                outreach.map((record) => (
                                    <OutreachRow key={record.email} record={record} topicId={id} />
                                ))
                            )}
                        </div>
                    </LemonWidget>
                </div>

                {/* Right column — topic metadata */}
                <div className="col-span-1 flex flex-col gap-4">
                    <LemonWidget title="Details">
                        <div className="p-3 space-y-3">
                            <DetailRow
                                label="Targeting"
                                value={
                                    topic.cohort_name ||
                                    (topic.interviewee_emails.length > 0 ? 'Email list' : 'Not set')
                                }
                            />
                            {topic.interviewee_emails.length > 0 && (
                                <div>
                                    <div className="text-xs font-semibold text-muted uppercase mb-1">Emails</div>
                                    <div className="text-sm space-y-0.5">
                                        {topic.interviewee_emails.map((e) => (
                                            <div key={e}>{e}</div>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <DetailRow label="Created" value={topic.created_at.split('T')[0]} />
                            <DetailRow label="Owner" value={topic.created_by?.first_name || '—'} />
                        </div>
                    </LemonWidget>

                    {topic.questions.length > 0 && (
                        <LemonWidget title="Interview questions">
                            <div className="p-3">
                                <LemonMarkdown>
                                    {topic.questions.map((q, i) => `${i + 1}. ${q}`).join('\n')}
                                </LemonMarkdown>
                            </div>
                        </LemonWidget>
                    )}

                    {topic.agent_context && (
                        <LemonWidget title="Agent context">
                            <div className="p-3">
                                <p className="text-sm mb-0">{topic.agent_context}</p>
                            </div>
                        </LemonWidget>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}

function StatCard({
    label,
    value,
    color,
}: {
    label: string
    value: number
    color: 'success' | 'warning' | 'primary' | 'muted' | 'danger'
}): JSX.Element {
    const borderColor = {
        success: 'border-success',
        warning: 'border-warning',
        primary: 'border-primary',
        muted: 'border-border',
        danger: 'border-danger',
    }[color]
    const textColor = {
        success: 'text-success',
        warning: 'text-warning',
        primary: 'text-primary',
        muted: 'text-muted',
        danger: 'text-danger',
    }[color]

    return (
        <div className={`rounded-lg border-2 ${borderColor} bg-bg-light p-3`}>
            <div className={`text-2xl font-bold ${textColor}`}>{value}</div>
            <div className="text-xs text-muted font-medium mt-0.5">{label}</div>
        </div>
    )
}

function DetailRow({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex justify-between">
            <span className="text-muted text-sm">{label}</span>
            <span className="text-sm font-medium">{value}</span>
        </div>
    )
}

function OutreachRow({ record, topicId }: { record: OutreachRecord; topicId: string }): JSX.Element {
    const { icon, label, color } = outreachStatusConfig(record.status)
    const hasDetail = record.status === 'completed'

    const content = (
        <div className={`p-3 ${hasDetail ? 'hover:bg-bg-light transition-colors' : ''}`}>
            <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                    <div>
                        <div className="font-medium text-sm">{record.name}</div>
                        <div className="text-xs text-muted">{record.email}</div>
                    </div>
                </div>
                <div className="flex items-center gap-1.5">
                    <div className={`flex items-center gap-1 text-xs font-medium ${color}`}>
                        {icon}
                        {label}
                    </div>
                    {hasDetail && <IconChevronRight className="text-muted" />}
                </div>
            </div>

            {record.interview_date && (
                <div className="text-xs text-muted mt-1">
                    {record.status === 'scheduled' ? 'Scheduled for' : 'Interviewed on'} {record.interview_date}
                </div>
            )}

            {record.learnings && (
                <div className="mt-2 p-2 rounded bg-bg-light text-sm">
                    <span className="font-semibold text-xs text-muted uppercase">Learnings: </span>
                    {record.learnings}
                </div>
            )}
        </div>
    )

    if (hasDetail) {
        return (
            <Link
                to={urls.userInterviewResponse(topicId, encodeURIComponent(record.email))}
                className="block no-underline text-current"
            >
                {content}
            </Link>
        )
    }

    return content
}
