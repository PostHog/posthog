import type { TaskRunStatus } from '@/model/types'
import { DEMO_BRIEFINGS, DEMO_DECISION } from './briefings'

// Stored run logs for the demo sessions in `chats.ts`, shaped like `GET tasks/{id}/runs/{run}/logs/` lines.

export interface DemoSessionLog {
    title: string
    status: TaskRunStatus
    entries: unknown[]
}

function notification(method: string, params: Record<string, unknown>): Record<string, unknown> {
    return { type: 'notification', notification: { jsonrpc: '2.0', method, params } }
}

function update(update: Record<string, unknown>): Record<string, unknown> {
    return notification('session/update', { sessionId: 'demo-session', update })
}

function userMessage(text: string): Record<string, unknown> {
    return update({ sessionUpdate: 'user_message_chunk', content: { type: 'text', text } })
}

function thought(text: string): Record<string, unknown> {
    return update({ sessionUpdate: 'agent_thought_chunk', content: { type: 'text', text } })
}

function agentMessage(text: string): Record<string, unknown> {
    return update({ sessionUpdate: 'agent_message', content: { type: 'text', text } })
}

function tool(
    toolCallId: string,
    toolName: string,
    kind: string,
    title: string,
    status: 'completed' | 'failed' = 'completed'
): Record<string, unknown>[] {
    return [
        update({
            sessionUpdate: 'tool_call',
            toolCallId,
            title,
            kind,
            status: 'pending',
            _meta: { claudeCode: { toolName } },
        }),
        update({ sessionUpdate: 'tool_call_update', toolCallId, status }),
    ]
}

function runStarted(runId: string): Record<string, unknown> {
    return notification('_posthog/run_started', { runId })
}

const TURN_COMPLETE = notification('_posthog/turn_complete', {})

const FLAKY_TEST_PR = 'https://github.com/example/app/pull/482'

const LOGS: Record<string, DemoSessionLog> = {
    'demo-session-flaky-test': {
        title: 'Fix the flaky checkout test',
        status: 'completed',
        entries: [
            runStarted('demo-run-flaky-test'),
            userMessage(
                'The checkout test fails about one run in five on CI. Find out why and fix it so it passes every time.'
            ),
            thought('The failure is intermittent, so a timing problem is likely. I will read the test first.'),
            ...tool('demo-tc-read-test', 'Read', 'read', 'Read /repo/web/tests/checkout.spec.ts'),
            ...tool('demo-tc-run-test', 'Bash', 'execute', 'pnpm test checkout.spec.ts --repeat 20'),
            thought('4 of 20 runs failed. Each failure clicks Pay before the shared folder quota loads.'),
            ...tool('demo-tc-read-page', 'Read', 'read', 'Read /repo/web/src/checkout/PayButton.tsx'),
            ...tool('demo-tc-edit-test', 'Edit', 'edit', 'Edit /repo/web/tests/checkout.spec.ts'),
            ...tool('demo-tc-rerun-test', 'Bash', 'execute', 'pnpm test checkout.spec.ts --repeat 50'),
            agentMessage(
                [
                    'The test clicked **Pay** before the storage quota request finished, so the button was sometimes still disabled.',
                    '',
                    '- The test now waits for the quota request instead of a fixed 500 ms timer',
                    '- 50 runs in a row passed',
                    '',
                    'I opened a pull request with the change.',
                ].join('\n')
            ),
            {
                type: 'task_run_state',
                run_id: 'demo-run-flaky-test',
                status: 'completed',
                stage: null,
                error_message: null,
                output: { pr_url: FLAKY_TEST_PR, pr_urls: [FLAKY_TEST_PR] },
            },
            TURN_COMPLETE,
        ],
    },
    'demo-session-dark-mode': {
        title: 'Add dark mode to settings',
        status: 'in_progress',
        entries: [
            runStarted('demo-run-dark-mode'),
            userMessage('Add a dark mode switch to the Hedgebox settings page.'),
            thought('Settings already has an appearance section. I will check how the theme is stored.'),
            ...tool('demo-tc-find-theme', 'Grep', 'search', 'Grep theme /repo/web/src/settings'),
            ...tool('demo-tc-read-settings', 'Read', 'read', 'Read /repo/web/src/settings/AppearanceSection.tsx'),
            agentMessage(
                'The app stores the theme per device. Before I add the switch, I need to know where the choice should live.'
            ),
            notification('_posthog/permission_request', {
                requestId: 'demo-req-dark-mode',
                options: [
                    { optionId: 'option_0', kind: 'allow_once', name: 'Save it per account' },
                    { optionId: 'option_1', kind: 'allow_once', name: 'Keep it per device' },
                ],
                toolCall: {
                    toolCallId: 'demo-tc-question',
                    title: 'Where should the dark mode choice live?',
                    kind: 'other',
                    _meta: {
                        claudeCode: { toolName: 'AskUserQuestion' },
                        codeToolKind: 'question',
                        questions: [
                            {
                                question: 'Where should the dark mode choice live?',
                                header: 'Theme',
                                multiSelect: false,
                                options: [
                                    {
                                        label: 'Save it per account',
                                        description: 'The same theme on every device you sign in on',
                                    },
                                    { label: 'Keep it per device', description: 'No server change' },
                                ],
                            },
                        ],
                    },
                },
            }),
        ],
    },
    'demo-session-webhooks': {
        title: 'Migrate billing webhooks',
        status: 'failed',
        entries: [
            runStarted('demo-run-webhooks'),
            userMessage('Move the billing webhooks from the old handler to the new events endpoint.'),
            thought('I will find the old handler and list the events it takes.'),
            ...tool('demo-tc-find-handler', 'Grep', 'search', 'Grep billing_webhook /repo/api'),
            ...tool('demo-tc-read-handler', 'Read', 'read', 'Read /repo/api/billing/webhooks.py'),
            ...tool('demo-tc-run-migrations', 'Bash', 'execute', 'python manage.py migrate billing', 'failed'),
            notification('_posthog/error', {
                message: "The sandbox couldn't reach the billing test database, so the migration did not run.",
            }),
            {
                type: 'task_run_state',
                run_id: 'demo-run-webhooks',
                status: 'failed',
                stage: null,
                error_message: "The sandbox couldn't reach the billing test database, so the migration did not run.",
                output: null,
            },
        ],
    },
}

/** A stored demo session, keyed by the task ids in `chats.ts`. Undefined for an id the demo does not know. */
export function demoSessionLog(taskId: string): DemoSessionLog | undefined {
    if (LOGS[taskId]) {
        return LOGS[taskId]
    }
    const reportId = taskId.replace(/(?:-handoff)?-task$/, '')
    const briefing = DEMO_BRIEFINGS.find((item) => item.id === reportId)
    if (!briefing) {
        return undefined
    }
    const runId = demoSessionRunId(taskId)
    const decision = briefing.kind === 'decision' && !taskId.endsWith('-handoff-task')
    const pullRequests = decision
        ? ['https://github.com/example/app/pull/4191']
        : briefing.kind === 'pr_ready'
          ? [4190, 4188, 4189, 4192].map((number) => `https://github.com/example/app/pull/${number}`)
          : []
    return {
        title: briefing.title,
        status: 'in_progress',
        entries: [
            runStarted(runId),
            userMessage(briefing.prompt ?? briefing.title),
            ...tool(`${reportId}-read`, 'Read', 'read', 'Read the report and related source'),
            agentMessage(
                decision ? DEMO_DECISION.question : 'You can review the task activity or send a follow-up here.'
            ),
            {
                type: 'task_run_state',
                run_id: runId,
                status: 'in_progress',
                stage: briefing.handedStage,
                output: { pr_url: pullRequests[0] ?? null, pr_urls: pullRequests },
            },
            ...(decision
                ? [
                      notification('_posthog/permission_request', {
                          requestId: DEMO_DECISION.id,
                          options: DEMO_DECISION.options.map((option, index) => ({
                              optionId: `option_${index}`,
                              kind: 'allow_once',
                              name: option.title,
                          })),
                          toolCall: {
                              toolCallId: `${reportId}-question`,
                              title: DEMO_DECISION.question,
                              kind: 'other',
                              _meta: {
                                  claudeCode: { toolName: 'AskUserQuestion' },
                                  codeToolKind: 'question',
                                  questions: [
                                      {
                                          question: DEMO_DECISION.question,
                                          multiSelect: false,
                                          options: DEMO_DECISION.options.map((option) => ({
                                              label: option.title,
                                              description: option.meta,
                                          })),
                                      },
                                  ],
                              },
                          },
                      }),
                  ]
                : [TURN_COMPLETE]),
        ],
    }
}

/** The run id the demo session's log names, so its frames count as the session's own run. */
export function demoSessionRunId(taskId: string): string {
    if (taskId.endsWith('-task')) {
        return `${taskId.slice(0, -5)}-run`
    }
    return `demo-run-${taskId.replace(/^demo-session-/, '')}`
}

export const DEMO_REPLY = [
    "This is the demo, so I can't look at your data.",
    '',
    'When you sign in, PostHog AI can:',
    '',
    '- explain what **caused** a report',
    '- check **who is affected** with a quick query',
    '- draft a **status update** you can paste anywhere',
    '',
    'Turn off the demo in Settings, then sign in to ask about your own reports.',
].join('\n')

/** What the demo agent says after an answered decision. */
export const DEMO_ANSWER_REPLY = 'Thanks. I will continue with that choice.'
