import type { HogFlowEditorActionMetrics } from '../../hogFlowEditorLogic'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../../types'

// Invented companies, people, and content. Every step uses a real step type or template and its real inputs.

type Config = Record<string, unknown>

const step = (id: string, type: HogFlowAction['type'], name: string, config: Config): HogFlowAction =>
    ({ id, type, name, description: '', config }) as HogFlowAction

const template = (
    id: string,
    name: string,
    templateId: string,
    inputs: Config,
    extra: Partial<HogFlowAction> = {}
): HogFlowAction =>
    ({
        ...step(id, 'function', name, {
            template_id: templateId,
            inputs: Object.fromEntries(Object.entries(inputs).map(([key, value]) => [key, { value }])),
        }),
        ...extra,
    }) as HogFlowAction

const slack = (id: string, name: string, channel: string, text: string): HogFlowAction =>
    template(id, name, 'template-slack', { slack_workspace: 1, channel, text })

const aiTask = (id: string, title: string, prompt: string, outputs: string[], skills: string[] = []): HogFlowAction =>
    template(
        id,
        title,
        'template-posthog-create-task',
        { title, prompt, skills },
        { output_variable: outputs.map((key) => ({ key, result_path: key })) }
    )

const emailHtml = (accent: string, heading: string, body: string, cta: string): string =>
    [
        '<html><body style="margin:0;background:#f5f5f4;font-family:Helvetica,Arial,sans-serif;color:#1f2937">',
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">',
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px">',
        `<tr><td style="padding:28px 40px 4px;font-size:14px;font-weight:700;color:${accent}">Example Co.</td></tr>`,
        `<tr><td style="padding:8px 40px"><h1 style="margin:0;font-size:26px;line-height:1.3">${heading}</h1></td></tr>`,
        `<tr><td style="padding:8px 40px;font-size:16px;line-height:1.6">${body}</td></tr>`,
        `<tr><td style="padding:24px 40px 40px"><a href="https://example.com" style="background:${accent};color:#ffffff;padding:12px 24px;border-radius:6px;text-decoration:none">${cta}</a></td></tr>`,
        '</table></td></tr></table></body></html>',
    ].join('')

const email = (id: string, subject: string, preheader: string, body: string, cta: string): HogFlowAction =>
    step(id, 'function_email', subject, {
        template_id: 'template-email',
        message_category_type: 'marketing',
        inputs: {
            email: {
                value: {
                    to: { name: '', email: '{{ person.properties.email }}' },
                    from: { integrationId: 1 },
                    subject,
                    preheader,
                    html: emailHtml('#6d28d9', subject, body, cta),
                    text: body,
                },
            },
        },
    })

const emailStep = (id: string, subject: string, preheader: string, html: string, text: string): HogFlowAction =>
    step(id, 'function_email', subject, {
        template_id: 'template-email',
        message_category_type: 'marketing',
        inputs: {
            email: {
                value: {
                    to: { name: '', email: '{{ person.properties.email }}' },
                    from: { integrationId: 1 },
                    subject,
                    preheader,
                    html,
                    text,
                },
            },
        },
    })

const FIRST_NAME = '{{ person.properties.first_name }}'
const LONG_LINK =
    'https://example.com/templates/onboarding/checklists/2026/q4/engineering-team-handbook-template-with-sections-for-architecture-decision-records-and-runbooks?utm_source=email&utm_medium=lifecycle'

const newsletterHtml = [
    '<html><body style="margin:0;background:#f5f5f4;font-family:Helvetica,Arial,sans-serif;color:#1f2937">',
    '<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff">',
    `<tr><td style="padding:24px 40px"><h1 style="margin:0;font-size:26px">Hi ${FIRST_NAME}, here is your October digest</h1></td></tr>`,
    '<tr><td style="padding:8px 40px"><div role="img" aria-label="A desk with a laptop" style="height:180px;background:#ede9fe">Image: a desk with a laptop</div></td></tr>',
    '<tr><td style="padding:8px 40px"><h2 style="font-size:20px">Shared templates</h2><p>Any doc can now become a template for the whole workspace. <a href="https://example.com/docs/templates">Read how templates work</a>.</p></td></tr>',
    '<tr><td style="padding:8px 40px"><h2 style="font-size:20px">What your team read most</h2><ul><li>Quarterly planning notes</li><li>Onboarding checklist for new engineers</li><li>Design review: settings page</li></ul></td></tr>',
    `<tr><td style="padding:8px 40px"><p>Reply to this email if there is something you want us to build next, ${FIRST_NAME}.</p></td></tr>`,
    '<tr><td style="padding:20px 40px"><a href="https://example.com/workspace" style="background:#6d28d9;color:#ffffff;padding:12px 24px">Open your workspace</a></td></tr>',
    '</table></body></html>',
].join('')

const eventTrigger = (event: string): Config => ({
    type: 'event',
    filters: { events: [{ id: event, name: event, type: 'events' }], properties: [], actions: [] },
})

const delay = (id: string, duration: string): HogFlowAction =>
    step(id, 'delay', `Wait ${duration}`, { delay_duration: duration })

const waitFor = (id: string, event: string, maxWait: string): HogFlowAction =>
    step(id, 'wait_until_condition', `Wait for ${event}`, {
        condition: { name: event, filters: { events: [{ id: event, name: event, type: 'events' }] } },
        max_wait_duration: maxWait,
    })

const split = (id: string, key: string, type: string, paths: [string, string, string?][]): HogFlowAction =>
    step(id, 'conditional_branch', `By ${key}`, {
        conditions: paths.map(([name, value, operator]) => ({
            name,
            filters: { properties: [{ key, type, value: [value], operator: operator ?? 'exact' }] },
        })),
    })

const exit = (id: string, reason: string): HogFlowAction => step(id, 'exit', 'Exit', { reason })

const next = (from: string, to: string): HogFlowEdge => ({ from, to, type: 'continue' })
const branch = (from: string, to: string, index: number): HogFlowEdge => ({ from, to, type: 'branch', index })

const flow = (id: string, name: string, actions: HogFlowAction[], edges: HogFlowEdge[]): HogFlow =>
    ({
        id,
        team_id: 1,
        version: 1,
        name,
        status: 'draft',
        exit_condition: 'exit_only_at_end',
        trigger: actions[0].config,
        variables: [],
        actions,
        edges,
        created_at: '2026-10-01T09:00:00.000Z',
        updated_at: '2026-10-10T12:00:00.000Z',
    }) as HogFlow

export const AI_SUPPORT_TRIAGE = flow(
    'storybook-tile-ai-triage',
    'AI support triage',
    [
        step('trigger_node', 'trigger', 'Ticket created', eventTrigger('Ticket created')),
        aiTask(
            'classify',
            'Sort the ticket',
            'Read the ticket. Pick a category (how_to, bug, billing) and an urgency from 1 to 3.',
            ['category', 'urgency'],
            ['support-categories']
        ),
        split('by_category', 'category', 'workflow_variable', [
            ['How-to', 'how_to'],
            ['Bug', 'bug'],
            ['Billing', 'billing'],
        ]),
        aiTask(
            'draft_reply',
            'Answer the question',
            'Answer the question with links to the docs. Say how sure you are from 0 to 1.',
            ['reply', 'confidence'],
            ['docs-search', 'tone-of-voice']
        ),
        split('by_confidence', 'confidence', 'workflow_variable', [['Sure', '0.8', 'gte']]),
        template('send_reply', 'Send reply', 'template-posthog-send-ticket-message', {
            ticket_id: '{event.properties.ticket_id}',
            message: '{variables.reply}',
            is_private: false,
        }),
        template('save_note', 'Save as note', 'template-posthog-send-ticket-message', {
            ticket_id: '{event.properties.ticket_id}',
            message: '{variables.reply}',
            is_private: true,
        }),
        template('tag_bug', 'Route to engineering', 'template-posthog-update-ticket', {
            ticket_id: '{event.properties.ticket_id}',
            priority: 'high',
            tags: ['bug'],
        }),
        slack('bug_slack', 'Tell engineering', 'C0123|#bugs', 'New bug ticket: {event.properties.subject}'),
        template('tag_billing', 'Route to billing', 'template-posthog-update-ticket', {
            ticket_id: '{event.properties.ticket_id}',
            status: 'pending',
            tags: ['billing'],
        }),
        exit('exit_node', 'Ticket triaged'),
    ],
    [
        next('trigger_node', 'classify'),
        next('classify', 'by_category'),
        branch('by_category', 'draft_reply', 0),
        next('draft_reply', 'by_confidence'),
        branch('by_confidence', 'send_reply', 0),
        next('by_confidence', 'save_note'),
        branch('by_category', 'tag_bug', 1),
        next('tag_bug', 'bug_slack'),
        branch('by_category', 'tag_billing', 2),
        next('by_category', 'exit_node'),
        next('send_reply', 'exit_node'),
        next('save_note', 'exit_node'),
        next('bug_slack', 'exit_node'),
        next('tag_billing', 'exit_node'),
    ]
)

export const TRIAL_TO_PAID = flow(
    'storybook-tile-trial-to-paid',
    'Convert trials to paid',
    [
        step('trigger_node', 'trigger', 'Trial started', eventTrigger('Trial started')),
        delay('wait_ten_days', '10d'),
        split('by_activation', 'docs_created', 'person', [['Active', '3', 'gte']]),
        email(
            'upgrade',
            'Keep your team’s docs after the trial',
            'Upgrade now and keep everything',
            'Your team wrote a lot this week. Upgrade to keep every doc and comment.',
            'Upgrade'
        ),
        split('by_seats', 'seats', 'person', [['10+ seats', '10', 'gte']]),
        slack('sales_slack', 'Tell sales', 'C0456|#sales-trials', 'Big trial is stuck: {person.properties.company}'),
        email(
            'help',
            'Need a hand getting started?',
            'Book 15 minutes with us',
            'It looks like you have not written many docs yet. We are happy to help.',
            'Book a call'
        ),
        waitFor('wait_upgrade', 'Upgraded', '4d'),
        exit('exit_converted', 'Converted to paid'),
        email(
            'last_day',
            'Your trial ends tomorrow',
            'Pick a plan to keep your docs',
            'Your trial ends tomorrow. Pick a plan so your team keeps working.',
            'Pick a plan'
        ),
        template('mark_churn_risk', 'Mark churn risk', 'template-posthog-update-person-properties', {
            set_properties: { churn_risk: 'high' },
        }),
        exit('exit_node', 'Trial ended'),
    ],
    [
        next('trigger_node', 'wait_ten_days'),
        next('wait_ten_days', 'by_activation'),
        branch('by_activation', 'upgrade', 0),
        next('by_activation', 'by_seats'),
        branch('by_seats', 'sales_slack', 0),
        next('by_seats', 'help'),
        next('sales_slack', 'wait_upgrade'),
        next('help', 'wait_upgrade'),
        next('upgrade', 'wait_upgrade'),
        branch('wait_upgrade', 'exit_converted', 0),
        next('wait_upgrade', 'last_day'),
        next('last_day', 'mark_churn_risk'),
        next('mark_churn_risk', 'exit_node'),
    ]
)

export const TICKET_TO_SLACK = flow(
    'storybook-tile-ticket-to-slack',
    'New support ticket to Slack',
    [
        step('trigger_node', 'trigger', 'Ticket created', eventTrigger('Ticket created')),
        split('by_priority', 'priority', 'event', [['Urgent', 'urgent']]),
        slack(
            'urgent_slack',
            'Urgent ticket',
            'C0789|#support-urgent',
            '@here Urgent ticket from {person.properties.email}: {event.properties.subject}'
        ),
        template('page_oncall', 'Page on-call', 'template-webhook', {
            url: 'https://events.example.com/v2/enqueue',
            method: 'POST',
            body: { severity: 'critical', summary: '{event.properties.subject}' },
        }),
        step('business_hours', 'wait_until_time_window', 'Business hours', {
            timezone: 'Europe/Berlin',
            day: 'weekday',
            time: ['09:00', '17:00'],
        }),
        slack(
            'ticket_slack',
            'New ticket',
            'C0790|#support',
            'New ticket from {person.properties.email}: {event.properties.subject}'
        ),
        exit('exit_node', 'Team notified'),
    ],
    [
        next('trigger_node', 'by_priority'),
        branch('by_priority', 'urgent_slack', 0),
        next('urgent_slack', 'page_oncall'),
        next('page_oncall', 'exit_node'),
        next('by_priority', 'business_hours'),
        next('business_hours', 'ticket_slack'),
        next('ticket_slack', 'exit_node'),
    ]
)

export const LONG_EMAILS = flow(
    'storybook-tile-long-emails',
    'Long emails',
    [
        step('trigger_node', 'trigger', 'Signed up', eventTrigger('Signed up')),
        emailStep(
            'newsletter',
            'Your October digest: shared templates, faster search, offline drafts, and the twelve docs your team opened most this month',
            `Everything new this month, the docs ${FIRST_NAME}'s team keeps coming back to, the shortcuts power users swear by, and a first look at November`,
            newsletterHtml,
            'Your October digest.'
        ),
        emailStep(
            'long_link',
            'Start from a template: example.com/templates/engineering-team-handbook-with-architecture-decision-records',
            'Supercalifragilisticdocumentationtemplategallerylaunchweekeditionforengineeringteams',
            emailHtml(
                '#6d28d9',
                'Start from a template',
                `The most copied template this week: <a href="${LONG_LINK}">${LONG_LINK}</a>`,
                'Browse the gallery'
            ),
            `The most copied template this week: ${LONG_LINK}`
        ),
        emailStep(
            'plain_text',
            'A quick note from the team about inviting your teammates',
            '',
            '',
            `Hi ${FIRST_NAME},\n\nDocs get better when two people look at them. You can invite three people for free from Settings, then Members.\n\nReply to this email if you have questions. A person reads every reply.`
        ),
        exit('exit_node', 'Welcome finished'),
    ],
    [
        next('trigger_node', 'newsletter'),
        next('newsletter', 'long_link'),
        next('long_link', 'plain_text'),
        next('plain_text', 'exit_node'),
    ]
)

export const TILE_CANVAS_WORKFLOWS: Record<string, HogFlow> = Object.fromEntries(
    [AI_SUPPORT_TRIAGE, TRIAL_TO_PAID, TICKET_TO_SLACK, LONG_EMAILS].map((workflow) => [workflow.id, workflow])
)

export const TRIAL_TO_PAID_METRICS: Record<string, HogFlowEditorActionMetrics> = Object.fromEntries(
    (
        [
            ['trigger_node', 4800, 0, 0],
            ['wait_ten_days', 4790, 0, 10],
            ['by_activation', 4790, 0, 0],
            ['upgrade', 3120, 12, 48],
            ['by_seats', 1610, 0, 0],
            ['sales_slack', 210, 0, 0],
            ['help', 1380, 8, 12],
            ['wait_upgrade', 4790, 0, 0],
            ['exit_converted', 960, 0, 0],
            ['last_day', 3790, 20, 20],
            ['mark_churn_risk', 3830, 0, 0],
            ['exit_node', 3830, 0, 0],
        ] as const
    ).map(([actionId, succeeded, failed, filtered]) => [actionId, { actionId, succeeded, failed, filtered }])
)
