import type { HogFlow, HogFlowAction } from '../types'

type Edge = HogFlow['edges'][number]

const BASE: Omit<HogFlow, 'id' | 'name' | 'description' | 'trigger' | 'actions' | 'edges' | 'variables'> = {
    team_id: 1,
    version: 4,
    status: 'active',
    exit_condition: 'exit_only_at_end',
    created_at: '2026-09-01T09:00:00.000Z',
    updated_at: '2026-09-04T12:00:00.000Z',
}

const eventTrigger = (id: string, name: string): HogFlow['trigger'] => ({
    type: 'event',
    filters: { events: [{ id, name, type: 'events' }], properties: [], actions: [] },
})

const input = (value: unknown, order: number): { order: number; value: unknown; templating: 'hog' } => ({
    order,
    value,
    templating: 'hog',
})

const variableCondition = (
    name: string,
    key: string,
    value: string | string[]
): { name: string; filters: { properties: any[] } } => ({
    name,
    filters: { properties: [{ key, type: 'workflow_variable', value, operator: 'exact' }] },
})

const groupCondition = (
    name: string,
    key: string,
    value: string
): { name: string; filters: { properties: any[] } } => ({
    name,
    filters: { properties: [{ key, type: 'group', value, operator: 'exact', group_type_index: 0 }] },
})

const exitAction = (reason: string): HogFlowAction =>
    ({ id: 'exit_node', type: 'exit', name: 'Exit', description: '', config: { reason } }) as HogFlowAction

const getTicket = (id: string, name: string, description: string): HogFlowAction =>
    ({
        id,
        type: 'function',
        name,
        description,
        config: {
            template_id: 'template-posthog-get-ticket',
            inputs: { ticket_id: input('{event.properties.ticket_id}', 0) },
        },
    }) as HogFlowAction

const emailAction = (id: string, name: string, subject: string, preheader: string, body: string): HogFlowAction =>
    ({
        id,
        type: 'function_email',
        name,
        description: '',
        config: {
            template_id: 'template-email',
            message_category_id: '019a0000-0000-0000-0000-000000000001',
            message_category_type: 'marketing',
            inputs: {
                email: {
                    order: 0,
                    templating: 'liquid',
                    value: {
                        to: { name: '', email: '{{ person.properties.email }}' },
                        from: { integrationId: 1 },
                        subject,
                        preheader,
                        html: `<html><body><h1>${subject}</h1><p>${body}</p></body></html>`,
                        text: body,
                    },
                },
            },
        },
    }) as HogFlowAction

const setPersonProperty = (id: string, name: string, sentLabel: string): HogFlowAction =>
    ({
        id,
        type: 'function',
        name,
        description: 'Set properties of a person in PostHog.',
        config: {
            template_id: 'template-posthog-capture',
            inputs: {
                distinct_id: input('{event.distinct_id}', 0),
                set_properties: input(
                    {
                        workflow_emails_sent: `{arrayPushBack(person.properties.workflow_emails_sent ?? [], '${sentLabel}')}`,
                    },
                    1
                ),
                set_once_properties: input({}, 2),
            },
        },
    }) as HogFlowAction

const slackAction = (id: string, name: string, text: string): HogFlowAction =>
    ({
        id,
        type: 'function',
        name,
        description: '',
        config: {
            template_id: 'template-slack',
            inputs: {
                slack_workspace: input(1, 0),
                channel: input('#alerts-example', 1),
                icon_emoji: input(':hedgehog:', 2),
                username: input('PostHog', 3),
                text: input(text, 4),
            },
        },
    }) as HogFlowAction

/**
 * Support SLA routing — walks a customer through segment checks and then a nine-way plan branch,
 * with a "is a tighter SLA already set?" guard in front of every write. 43 nodes, 79 edges.
 */
const supportSlaRouting = (): HogFlow => {
    const actions: HogFlowAction[] = []
    const edges: Edge[] = []

    const updateTicket = (id: string, name: string, tag: string, amount: number): HogFlowAction =>
        ({
            id,
            type: 'function',
            name,
            description: `Add the ${tag} tag and set a ${amount} hour SLA`,
            config: {
                template_id: 'template-posthog-update-ticket',
                inputs: {
                    ticket_id: input('{event.properties.ticket_id}', 0),
                    sla_amount: input(String(amount), 1),
                    sla_unit: input('hour', 2),
                    sla_business_hours: input(
                        {
                            days: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
                            time: ['09:00', '17:00'],
                            timezone: 'UTC',
                        },
                        3
                    ),
                    tags: input([tag], 4),
                    tags_mode: input('add', 5),
                },
            },
        }) as HogFlowAction

    // Every SLA write sits behind a guard that exits when the ticket already has a tighter deadline.
    const guardedWrite = (key: string, label: string, tag: string, hours: number): string => {
        const guardId = `guard_${key}`
        const writeId = `set_sla_${key}`
        actions.push({
            id: guardId,
            type: 'conditional_branch',
            name: `${label} SLA guard`,
            description: 'Skip the write when the existing SLA is already tighter.',
            config: { conditions: [variableCondition('Existing SLA is tighter', 'ticket_sla_is_tighter', ['true'])] },
        } as HogFlowAction)
        actions.push(updateTicket(writeId, `${label} ticket`, tag, hours))
        edges.push({ from: guardId, to: 'exit_node', type: 'branch', index: 0 })
        edges.push({ from: guardId, to: writeId, type: 'continue' })
        edges.push({ from: writeId, to: 'exit_node', type: 'continue' })
        return guardId
    }

    actions.push({
        id: 'trigger_node',
        type: 'trigger',
        name: 'Response from the customer',
        description: 'New response received',
        config: eventTrigger('$conversation_message_received', 'Ticket message received'),
    } as HogFlowAction)
    actions.push(getTicket('get_ticket', 'Get ticket', 'Load the ticket so its tags and SLA are available.'))
    actions.push({
        id: 'check_exclusions',
        type: 'conditional_branch',
        name: 'Check for exclusions',
        description: 'Skip tickets from the excluded channel, the excluded inboxes, or a new ticket.',
        config: {
            conditions: [
                variableCondition('From the excluded channel', 'ticket_slack_channel_id', 'C00EXAMPLE1'),
                variableCondition('Sent to shop@', 'ticket_email_to', ['shop@example.com']),
                variableCondition('Sent to abuse@', 'ticket_email_to', ['abuse@example.com']),
                variableCondition('Ticket status is new', 'ticket_status', ['new']),
            ],
        },
    } as HogFlowAction)
    edges.push({ from: 'trigger_node', to: 'get_ticket', type: 'continue' })
    edges.push({ from: 'get_ticket', to: 'check_exclusions', type: 'continue' })
    for (const index of [0, 1, 2, 3]) {
        edges.push({ from: 'check_exclusions', to: 'exit_node', type: 'branch', index })
    }

    // Segments are checked one after another, each falling through to the next.
    const segments = [
        {
            key: 'top-accounts',
            label: 'Top accounts',
            tag: 'segment_top_accounts',
            hours: 2,
            property: 'is_top_account',
        },
        { key: 'churn-risk', label: 'Churn risk', tag: 'segment_churn_risk', hours: 2, property: 'is_churn_risk' },
        { key: 'onboarding', label: 'Onboarding', tag: 'segment_onboarding', hours: 8, property: 'is_onboarding' },
    ]
    let fallthroughFrom = 'check_exclusions'
    for (const segment of segments) {
        const checkId = `check_${segment.key}`
        actions.push({
            id: checkId,
            type: 'conditional_branch',
            name: `Check if ${segment.label.toLowerCase()}`,
            description: '',
            config: { conditions: [groupCondition(segment.label, segment.property, 'true')] },
        } as HogFlowAction)
        edges.push({ from: fallthroughFrom, to: checkId, type: 'continue' })
        const guardId = guardedWrite(segment.key, segment.label, segment.tag, segment.hours)
        edges.push({ from: checkId, to: guardId, type: 'branch', index: 0 })
        fallthroughFrom = checkId
    }

    const plans = [
        { key: 'enterprise', label: 'Enterprise', tag: 'plan_enterprise', hours: 4 },
        { key: 'enterprise-managed', label: 'Enterprise (managed)', tag: 'plan_enterprise_managed', hours: 4 },
        { key: 'scale', label: 'Scale', tag: 'plan_scale', hours: 16 },
        { key: 'growth', label: 'Growth', tag: 'plan_growth', hours: 32 },
        { key: 'teams', label: 'Teams', tag: 'plan_teams', hours: 16 },
        { key: 'paid', label: 'Paid', tag: 'plan_paid', hours: 32 },
        { key: 'free', label: 'Free', tag: 'plan_free', hours: 48 },
        { key: 'startup', label: 'Startup', tag: 'plan_startup', hours: 32 },
        { key: 'accelerator', label: 'Accelerator', tag: 'plan_accelerator', hours: 16 },
    ]
    actions.push({
        id: 'check_plan',
        type: 'conditional_branch',
        name: 'Check billing plan',
        description: 'Check the billing plan for every customer that matched no segment.',
        config: { conditions: plans.map((plan) => groupCondition(plan.label, 'billing_plan', plan.key)) },
    } as HogFlowAction)
    edges.push({ from: fallthroughFrom, to: 'check_plan', type: 'continue' })
    plans.forEach((plan, index) => {
        const guardId = guardedWrite(plan.key, plan.label, plan.tag, plan.hours)
        edges.push({ from: 'check_plan', to: guardId, type: 'branch', index })
    })

    actions.push({
        id: 'check_shared_channel',
        type: 'conditional_branch',
        name: 'Check shared channel',
        description: 'Customers with a shared channel get a default SLA instead of an alert.',
        config: {
            conditions: [
                variableCondition('Has a shared Slack channel', 'ticket_channel_kind', ['slack']),
                variableCondition('Has a shared Teams channel', 'ticket_channel_kind', ['teams']),
            ],
        },
    } as HogFlowAction)
    edges.push({ from: 'check_plan', to: 'check_shared_channel', type: 'continue' })
    edges.push({
        from: 'check_shared_channel',
        to: guardedWrite('slack-default', 'Shared Slack channel default', 'channel_slack_default', 16),
        type: 'branch',
        index: 0,
    })
    edges.push({
        from: 'check_shared_channel',
        to: guardedWrite('teams-default', 'Shared Teams channel default', 'channel_teams_default', 16),
        type: 'branch',
        index: 1,
    })

    actions.push({
        id: 'check_contact_route',
        type: 'conditional_branch',
        name: 'Check the page or inbox the reply came from',
        description: '',
        config: {
            conditions: [
                variableCondition('Replied from /login', 'ticket_page', ['/login']),
                variableCondition('Replied from /signup', 'ticket_page', ['/signup']),
                variableCondition('Emailed billing@', 'ticket_email_to', ['billing@example.com']),
            ],
        },
    } as HogFlowAction)
    edges.push({ from: 'check_shared_channel', to: 'check_contact_route', type: 'continue' })
    const loginGuard = guardedWrite('login-default', 'Login default', 'unknown_login_default', 8)
    const billingGuard = guardedWrite('billing-default', 'Billing default', 'unknown_billing_default', 32)
    edges.push({ from: 'check_contact_route', to: loginGuard, type: 'branch', index: 0 })
    edges.push({ from: 'check_contact_route', to: loginGuard, type: 'branch', index: 1 })
    edges.push({ from: 'check_contact_route', to: billingGuard, type: 'branch', index: 2 })

    actions.push(
        slackAction(
            'alert_unmatched',
            'Alert the support channel',
            'A ticket matched no segment, plan, or channel and needs triage by hand.'
        )
    )
    edges.push({ from: 'check_contact_route', to: 'alert_unmatched', type: 'continue' })
    edges.push({ from: 'alert_unmatched', to: 'exit_node', type: 'continue' })
    actions.push(exitAction('Default exit'))

    return {
        ...BASE,
        id: 'example-support-sla-routing',
        name: 'Support SLA routing by segment and plan',
        description:
            'Runs when a customer replies to a ticket. Checks segments in priority order, then the billing plan, and sets a response-time SLA plus a matching tag. Every write is guarded so a tighter existing SLA is never overwritten.',
        trigger: eventTrigger('$conversation_message_received', 'Ticket message received'),
        variables: [
            { key: 'ticket_status', type: 'string', label: 'Status', default: '' },
            { key: 'ticket_priority', type: 'string', label: 'Priority', default: '' },
            { key: 'ticket_number', type: 'string', label: 'Number', default: '' },
            { key: 'ticket_subject', type: 'string', label: 'Subject', default: '' },
            { key: 'ticket_email_to', type: 'string', label: 'Sent to', default: '' },
            { key: 'ticket_page', type: 'string', label: 'Page', default: '' },
            { key: 'ticket_slack_channel_id', type: 'string', label: 'Slack channel', default: '' },
            { key: 'ticket_channel_kind', type: 'string', label: 'Channel kind', default: '' },
            { key: 'ticket_sla_due_at', type: 'string', label: 'SLA due at', default: '' },
            { key: 'ticket_sla_is_tighter', type: 'string', label: 'Existing SLA is tighter', default: '' },
        ],
        actions,
        edges,
    }
}

/**
 * Renewal alerting — a short gate chain that fans out into seven mutually exclusive Slack pings.
 * 15 nodes, 25 edges.
 */
const renewalWindowAlerts = (): HogFlow => {
    const pings = [
        {
            id: 'ping_renewal_over',
            name: 'Ping: credit runs out early',
            text: 'Credit runs out before the renewal date.',
        },
        {
            id: 'ping_renewal_under',
            name: 'Ping: credit left at renewal',
            text: 'Credit is left over at the renewal date.',
        },
        { id: 'ping_renewal_on12', name: 'Ping: on track, 12 month', text: 'On track on a 12 month contract.' },
        {
            id: 'ping_renewal_multi',
            name: 'Ping: on track, multi-year',
            text: 'On track on a multi-year contract that is ending.',
        },
        {
            id: 'ping_instalment_over',
            name: 'Ping: gap before the instalment',
            text: 'Credit runs out before the next instalment.',
        },
        {
            id: 'ping_instalment_under',
            name: 'Ping: credit left at the instalment',
            text: 'Credit is left over at the next instalment.',
        },
        {
            id: 'ping_instalment_on',
            name: 'Ping: instalment on track',
            text: 'Usage is on track for the next instalment.',
        },
    ]

    const actions: HogFlowAction[] = [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Contract phase becomes renewal window',
            description: '',
            config: eventTrigger('$account_custom_property_changed', 'Account custom property changed'),
        } as HogFlowAction,
        {
            id: 'get_account',
            type: 'function',
            name: 'Fetch the account',
            description: 'Loads the account so the message can name the managing team.',
            on_error: 'continue',
            output_variable: { key: 'account' },
            config: {
                template_id: 'template-posthog-get-account',
                inputs: { external_id: input('{event.properties.account_external_id}', 0) },
            },
        } as HogFlowAction,
        {
            id: 'gate_managed',
            type: 'conditional_branch',
            name: 'Account has a managing team?',
            description: '',
            config: { conditions: [groupCondition('Has a managing team', 'account_team', 'set')] },
        } as HogFlowAction,
        {
            id: 'gate_signed',
            type: 'conditional_branch',
            name: 'Renewal already signed?',
            description: '',
            config: { conditions: [groupCondition('Already signed', 'renewal_signed', 'true')] },
        } as HogFlowAction,
        {
            id: 'branch_next_event',
            type: 'conditional_branch',
            name: 'Next event: instalment or contract end?',
            description: '',
            config: {
                conditions: [
                    groupCondition('Next instalment', 'next_contract_event', 'instalment'),
                    groupCondition('Contract end', 'next_contract_event', 'contract_end'),
                ],
            },
        } as HogFlowAction,
        {
            id: 'band_renewal',
            type: 'conditional_branch',
            name: 'Renewal: usage band and term',
            description: '',
            config: {
                conditions: [
                    groupCondition('Runs out early', 'usage_band', 'over'),
                    groupCondition('Credit left over', 'usage_band', 'under'),
                    groupCondition('On track, 12 month', 'usage_band', 'on_track_12'),
                    groupCondition('On track, multi-year', 'usage_band', 'on_track_multi'),
                ],
            },
        } as HogFlowAction,
        {
            id: 'band_instalment',
            type: 'conditional_branch',
            name: 'Instalment: usage band',
            description: '',
            config: {
                conditions: [
                    groupCondition('Runs out early', 'usage_band', 'over'),
                    groupCondition('Credit left over', 'usage_band', 'under'),
                    groupCondition('On track', 'usage_band', 'on_track'),
                ],
            },
        } as HogFlowAction,
        ...pings.map((ping) => slackAction(ping.id, ping.name, ping.text)),
        exitAction('Done'),
    ]

    const edges: Edge[] = [
        { from: 'trigger_node', to: 'get_account', type: 'continue' },
        { from: 'get_account', to: 'gate_managed', type: 'continue' },
        { from: 'gate_managed', to: 'gate_signed', type: 'branch', index: 0 },
        { from: 'gate_managed', to: 'exit_node', type: 'continue' },
        { from: 'gate_signed', to: 'exit_node', type: 'branch', index: 0 },
        { from: 'gate_signed', to: 'branch_next_event', type: 'continue' },
        { from: 'branch_next_event', to: 'band_instalment', type: 'branch', index: 0 },
        { from: 'branch_next_event', to: 'band_renewal', type: 'branch', index: 1 },
        { from: 'branch_next_event', to: 'exit_node', type: 'continue' },
        { from: 'band_renewal', to: 'ping_renewal_over', type: 'branch', index: 0 },
        { from: 'band_renewal', to: 'ping_renewal_under', type: 'branch', index: 1 },
        { from: 'band_renewal', to: 'ping_renewal_on12', type: 'branch', index: 2 },
        { from: 'band_renewal', to: 'ping_renewal_multi', type: 'branch', index: 3 },
        { from: 'band_renewal', to: 'exit_node', type: 'continue' },
        { from: 'band_instalment', to: 'ping_instalment_over', type: 'branch', index: 0 },
        { from: 'band_instalment', to: 'ping_instalment_under', type: 'branch', index: 1 },
        { from: 'band_instalment', to: 'ping_instalment_on', type: 'branch', index: 2 },
        { from: 'band_instalment', to: 'exit_node', type: 'continue' },
        ...pings.map((ping): Edge => ({ from: ping.id, to: 'exit_node', type: 'continue' })),
    ]

    return {
        ...BASE,
        id: 'example-renewal-window-alerts',
        name: 'Renewal window alerts',
        description:
            'Pings the account owner when a contract enters its renewal window. Skips signed renewals, then routes by the next contract event and the usage band to one of seven messages.',
        trigger: eventTrigger('$account_custom_property_changed', 'Account custom property changed'),
        variables: [],
        actions,
        edges,
    }
}

/**
 * Pending ticket cleanup — long, mostly linear, with three delays and a re-check before each send.
 * 15 nodes, 21 edges.
 */
const pendingTicketCleanup = (): HogFlow => {
    const actions: HogFlowAction[] = [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Ticket becomes pending',
            description: '',
            config: eventTrigger('$conversation_ticket_status_changed', 'Ticket status changed'),
        } as HogFlowAction,
        {
            id: 'delay_five_days',
            type: 'delay',
            name: 'Wait five days',
            description: '',
            config: { delay_duration: '5d' },
        } as HogFlowAction,
        getTicket('get_ticket', 'Get ticket', 'Load the ticket before deciding whether to warn.'),
        {
            id: 'check_exclusions',
            type: 'conditional_branch',
            name: 'Check for exclusions',
            description: '',
            config: {
                conditions: [
                    variableCondition('From the excluded channel', 'ticket_slack_channel_id', 'C00EXAMPLE1'),
                    variableCondition('Sent to shop@', 'ticket_email_to', ['shop@example.com']),
                    variableCondition('Sent to abuse@', 'ticket_email_to', ['abuse@example.com']),
                    variableCondition('Excluded from reporting', 'ticket_tags', ['exclude_from_reporting']),
                ],
            },
        } as HogFlowAction,
        {
            id: 'check_pending',
            type: 'conditional_branch',
            name: 'Still pending?',
            description: '',
            config: { conditions: [variableCondition('Still pending', 'ticket_status', ['pending'])] },
        } as HogFlowAction,
        emailAction(
            'email_warning',
            'Warning email',
            'We will close this ticket soon',
            'Reply to keep it open',
            'We have not heard back for five days. Reply and we will pick this up again.'
        ),
        {
            id: 'delay_two_days',
            type: 'delay',
            name: 'Wait two days',
            description: '',
            config: { delay_duration: '2d' },
        } as HogFlowAction,
        getTicket('get_ticket_again', 'Get ticket again', 'Re-read the ticket after the warning.'),
        {
            id: 'check_pending_again',
            type: 'conditional_branch',
            name: 'Still pending after the warning?',
            description: '',
            config: { conditions: [variableCondition('Still pending', 'ticket_status', ['pending'])] },
        } as HogFlowAction,
        {
            id: 'resolve_ticket',
            type: 'function',
            name: 'Resolve the ticket',
            description: '',
            config: {
                template_id: 'template-posthog-update-ticket',
                inputs: {
                    ticket_id: input('{event.properties.ticket_id}', 0),
                    status: input('resolved', 1),
                    tags_mode: input('add', 2),
                },
            },
        } as HogFlowAction,
        {
            id: 'delay_one_day',
            type: 'delay',
            name: 'Wait 24 hours',
            description: '',
            config: { delay_duration: '1d' },
        } as HogFlowAction,
        getTicket('recheck_ticket', 'Re-check the ticket', 'Only survey tickets that are still resolved.'),
        {
            id: 'check_resolved',
            type: 'conditional_branch',
            name: 'Still resolved?',
            description: '',
            config: { conditions: [variableCondition('Still resolved', 'ticket_status', ['resolved'])] },
        } as HogFlowAction,
        emailAction(
            'email_survey',
            'Satisfaction survey',
            'How did we do?',
            'One question, one click',
            'Your ticket is closed. Tell us how the support went.'
        ),
        exitAction('Default exit'),
    ]

    const edges: Edge[] = [
        { from: 'trigger_node', to: 'delay_five_days', type: 'continue' },
        { from: 'delay_five_days', to: 'get_ticket', type: 'continue' },
        { from: 'get_ticket', to: 'check_exclusions', type: 'continue' },
        { from: 'check_exclusions', to: 'exit_node', type: 'branch', index: 0 },
        { from: 'check_exclusions', to: 'exit_node', type: 'branch', index: 1 },
        { from: 'check_exclusions', to: 'exit_node', type: 'branch', index: 2 },
        { from: 'check_exclusions', to: 'exit_node', type: 'branch', index: 3 },
        { from: 'check_exclusions', to: 'check_pending', type: 'continue' },
        { from: 'check_pending', to: 'email_warning', type: 'branch', index: 0 },
        { from: 'check_pending', to: 'exit_node', type: 'continue' },
        { from: 'email_warning', to: 'delay_two_days', type: 'continue' },
        { from: 'delay_two_days', to: 'get_ticket_again', type: 'continue' },
        { from: 'get_ticket_again', to: 'check_pending_again', type: 'continue' },
        { from: 'check_pending_again', to: 'resolve_ticket', type: 'branch', index: 0 },
        { from: 'check_pending_again', to: 'exit_node', type: 'continue' },
        { from: 'resolve_ticket', to: 'delay_one_day', type: 'continue' },
        { from: 'delay_one_day', to: 'recheck_ticket', type: 'continue' },
        { from: 'recheck_ticket', to: 'check_resolved', type: 'continue' },
        { from: 'check_resolved', to: 'email_survey', type: 'branch', index: 0 },
        { from: 'check_resolved', to: 'exit_node', type: 'continue' },
        { from: 'email_survey', to: 'exit_node', type: 'continue' },
    ]

    return {
        ...BASE,
        id: 'example-pending-ticket-cleanup',
        name: 'Close tickets that stay pending',
        description:
            'Warns on day five, closes the ticket on day seven if nobody replied, then sends a satisfaction survey a day later when the ticket is still closed.',
        trigger: eventTrigger('$conversation_ticket_status_changed', 'Ticket status changed'),
        variables: [
            { key: 'ticket_status', type: 'string', label: 'Status', default: '' },
            { key: 'ticket_email_to', type: 'string', label: 'Sent to', default: '' },
            { key: 'ticket_tags', type: 'string', label: 'Tags', default: '' },
            { key: 'ticket_slack_channel_id', type: 'string', label: 'Slack channel', default: '' },
        ],
        actions,
        edges,
    }
}

/**
 * Add-on promotion — a wide email split where each send is followed by its own person-property write.
 * 14 nodes, 19 edges.
 */
const addOnPromotionEmails = (): HogFlow => {
    const paths = [
        { key: 'seat_growth', subject: 'Your team is growing', label: 'Seat growth' },
        { key: 'flag_usage', subject: 'You are running a lot of flags', label: 'Flag usage' },
        { key: 'project_count', subject: 'Time for another project?', label: 'Project count' },
        { key: 'follow_up_a', subject: 'One more thing about add-ons', label: 'Follow-up A' },
        { key: 'follow_up_b', subject: 'A different angle on add-ons', label: 'Follow-up B' },
    ]

    const emailId = (key: string): string => `email_${key}`
    const writeId = (key: string): string => `record_${key}`

    const actions: HogFlowAction[] = [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'No add-on and revenue above the threshold',
            description: '',
            config: eventTrigger('organization usage report', 'Organization usage report'),
        } as HogFlowAction,
        {
            id: 'branch_signal',
            type: 'conditional_branch',
            name: 'Which growth signal fired?',
            description: '',
            config: {
                conditions: [
                    groupCondition('Seat growth', 'growth_signal', 'seats'),
                    groupCondition('Flag usage', 'growth_signal', 'flags'),
                    groupCondition('Project count', 'growth_signal', 'projects'),
                    groupCondition('Nothing specific', 'growth_signal', 'generic'),
                ],
            },
        } as HogFlowAction,
        {
            id: 'branch_second_email',
            type: 'conditional_branch',
            name: 'Send a second email?',
            description: '',
            config: {
                conditions: [
                    groupCondition('First follow-up', 'follow_up_stage', 'first'),
                    groupCondition('Second follow-up', 'follow_up_stage', 'second'),
                ],
            },
        } as HogFlowAction,
        ...paths.flatMap((path) => [
            emailAction(
                emailId(path.key),
                path.label,
                path.subject,
                'A quick look at what the add-ons do',
                'Here is what the Growth and Scale add-ons change for a workspace your size.'
            ),
            setPersonProperty(writeId(path.key), 'Update person property', path.subject),
        ]),
        exitAction('Default exit'),
    ]

    const edges: Edge[] = [
        { from: 'trigger_node', to: 'branch_signal', type: 'continue' },
        { from: 'branch_signal', to: emailId('seat_growth'), type: 'branch', index: 0 },
        { from: 'branch_signal', to: emailId('flag_usage'), type: 'branch', index: 1 },
        { from: 'branch_signal', to: emailId('project_count'), type: 'branch', index: 2 },
        { from: 'branch_signal', to: 'branch_second_email', type: 'branch', index: 3 },
        { from: 'branch_signal', to: 'exit_node', type: 'continue' },
        { from: 'branch_second_email', to: emailId('follow_up_a'), type: 'branch', index: 0 },
        { from: 'branch_second_email', to: emailId('follow_up_b'), type: 'branch', index: 1 },
        { from: 'branch_second_email', to: 'exit_node', type: 'continue' },
        ...paths.flatMap((path): Edge[] => [
            { from: emailId(path.key), to: writeId(path.key), type: 'continue' },
            { from: writeId(path.key), to: 'exit_node', type: 'continue' },
        ]),
    ]

    return {
        ...BASE,
        id: 'example-add-on-promotion-emails',
        name: 'Promote add-ons from a growth signal',
        description:
            'Splits on which growth signal fired, sends the matching email, and records the send on the person so the same email never goes out twice.',
        trigger: eventTrigger('organization usage report', 'Organization usage report'),
        variables: [{ key: 'growth_signal', type: 'string', label: 'Growth signal', default: '' }],
        actions,
        edges,
    }
}

/**
 * Redacted stand-ins for the busiest workflows running in production, matched node for node and
 * edge for edge. Names, filters, channels, addresses, and email bodies are invented.
 */
export const EXAMPLE_WORKFLOWS: Record<string, HogFlow> = Object.fromEntries(
    [supportSlaRouting(), renewalWindowAlerts(), pendingTicketCleanup(), addOnPromotionEmails()].map((flow) => [
        flow.id,
        flow,
    ])
)

export const EXAMPLE_WORKFLOW_IDS = Object.keys(EXAMPLE_WORKFLOWS)
