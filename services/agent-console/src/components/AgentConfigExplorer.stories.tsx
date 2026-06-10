import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { BundleFile } from '@posthog/agent-chat/fixtures'
import { weeklyDigest, weeklyDigestRevisions } from '@posthog/agent-chat/fixtures'

import { AgentConfigExplorer } from './AgentConfigExplorer'
import { RevisionBar } from './RevisionBar'

// A rich SRE-bot-shaped revision: multiple triggers, native + custom +
// client tools (one approval-gated), skills with nested SKILL.md bodies,
// an MCP, secrets (some unset), limits, and multi-mode auth.
const spec: Record<string, unknown> = {
    model: 'anthropic/claude-sonnet-4-6',
    reasoning: 'high',
    triggers: [
        {
            type: 'webhook',
            config: { path: '/webhook' },
            auth: {
                modes: [
                    { type: 'shared_secret', header: 'X-Webhook-Secret', secret_ref: 'WEBHOOK_SECRET' },
                    { type: 'posthog' },
                ],
            },
        },
        { type: 'slack', config: { mention_only: true, trusted_workspaces: ['T0XXXXXXX'] } },
        {
            type: 'chat',
            config: { allow_restart: false },
            auth: { modes: [{ type: 'posthog', scopes: [] }] },
        },
        {
            type: 'mcp',
            config: {},
            auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
        },
        { type: 'cron', config: { name: 'daily-digest', schedule: '0 9 * * *', prompt: 'Post the daily digest.' } },
    ],
    tools: [
        { kind: 'native', id: '@posthog/query' },
        { kind: 'native', id: '@posthog/memory-search' },
        { kind: 'native', id: '@posthog/memory-read' },
        {
            kind: 'native',
            id: '@posthog/memory-write',
            requires_approval: true,
            approval_policy: { approvers: ['team_admins'], allow_edit: true },
        },
        { kind: 'custom', id: 'incident-digest', path: 'tools/incident-digest/' },
        {
            kind: 'client',
            id: 'focus_session',
            description: 'Open one session in the sessions panel. Drives the console read pane; a no-op outside it.',
        },
    ],
    skills: [
        {
            id: 'triage-playbook',
            path: 'skills/triage-playbook/SKILL.md',
            description: 'Structured triage flow — load when starting an investigation.',
        },
        {
            id: 'runbook-memory',
            path: 'skills/runbook-memory/SKILL.md',
            description: 'The runbook corpus taxonomy + the approval-gated propose-and-link flow.',
        },
    ],
    mcps: [
        {
            id: 'incident-io',
            url: 'https://mcp.incident.io/mcp',
            secrets: ['INCIDENT_IO_TOKEN'],
            tools: ['incidents-list', { name: 'incidents-create', requires_approval: true }],
        },
    ],
    integrations: ['slack', 'github'],
    secrets: ['INCIDENT_IO_TOKEN'],
    limits: { max_turns: 30, max_tool_calls: 100, max_wall_seconds: 600 },
}

const files: BundleFile[] = [
    {
        path: 'agent.md',
        language: 'markdown',
        content:
            '# SRE triage assistant\n\nYou react to alerts in Slack, gather context, and post a clear hypothesis.\n\n## The loop\n\n1. Acknowledge fast.\n2. Check the runbook corpus + prior incidents.\n3. Form a hypothesis backed by evidence.',
    },
    {
        path: 'skills/triage-playbook/SKILL.md',
        language: 'markdown',
        content:
            '---\nname: triage-playbook\ndescription: Structured triage flow.\n---\n\n# Triage playbook\n\n## Phase 1 — context\n\nGather the facts before forming any hypothesis: what fired, where in the stack, blast radius.',
    },
    {
        path: 'skills/runbook-memory/SKILL.md',
        language: 'markdown',
        content:
            '# Runbook memory\n\nYour durable knowledge lives in agent memory under `runbooks/`:\n\n- `runbooks/alerts/<signature>.md`\n- `runbooks/systems/<area>.md`\n- `runbooks/procedures/<task>.md`\n\n**Writes are approval-gated** — you propose, a human approves.',
    },
    {
        path: 'tools/incident-digest/source.ts',
        language: 'typescript',
        content:
            'export default {\n    actions: {\n        default: async (args: { incidentId: string }) => ({ digest: `summary for ${args.incidentId}` }),\n    },\n}',
    },
    {
        path: 'tools/incident-digest/schema.json',
        language: 'json',
        content: JSON.stringify(
            {
                description: 'Summarize an incident timeline.',
                args_schema: { type: 'object', properties: { incidentId: { type: 'string' } } },
            },
            null,
            2
        ),
    },
]

// Only SLACK_BOT_TOKEN is set → SLACK_SIGNING_SECRET + INCIDENT_IO_TOKEN
// show "needs attention" (slack trigger, incident-io MCP, secrets section).
const base = {
    spec,
    files,
    agentSlug: 'sre-slack-bot',
    setSecrets: ['SLACK_BOT_TOKEN'],
    onEditSecret: (key: string): void => {
        // eslint-disable-next-line no-console
        console.info(`[story] open secret editor for ${key}`)
    },
    onAddCustomSecret: (): void => {
        // eslint-disable-next-line no-console
        console.info('[story] add custom secret')
    },
    // The host fills this with the live `<SlackSetupCard>`; a placeholder here.
    slackSetup: (
        <div className="p-4 text-xs text-muted-foreground">
            Slack app-manifest setup renders here (live <code className="font-mono">SlackSetupCard</code> in the app).
        </div>
    ),
}

const meta: Meta<typeof AgentConfigExplorer> = {
    title: 'Agent console components/AgentConfigExplorer (experimental)',
    component: AgentConfigExplorer,
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <div className="h-screen p-6">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof AgentConfigExplorer>

export const Default: Story = { args: base }
export const ToolsSection: Story = { args: { ...base, selectedPath: 'cfg:tools' } }
export const SkillsSection: Story = { args: { ...base, selectedPath: 'cfg:skills' } }
export const AGatedNativeTool: Story = { args: { ...base, selectedPath: 'cfg:tool/@posthog/memory-write' } }
export const ACustomTool: Story = { args: { ...base, selectedPath: 'cfg:tool/incident-digest' } }
export const AClientTool: Story = { args: { ...base, selectedPath: 'cfg:tool/focus_session' } }
export const ASkill: Story = { args: { ...base, selectedPath: 'cfg:skill/runbook-memory' } }
export const Instructions: Story = { args: { ...base, selectedPath: 'cfg:instructions' } }
export const SecretsSection: Story = { args: { ...base, selectedPath: 'cfg:secrets' } }
export const AMissingSecret: Story = { args: { ...base, selectedPath: 'cfg:secret/INCIDENT_IO_TOKEN' } }
export const ATriggerSecret: Story = { args: { ...base, selectedPath: 'cfg:secret/SLACK_SIGNING_SECRET' } }
export const AnMcpMissingSecret: Story = { args: { ...base, selectedPath: 'cfg:mcp/incident-io' } }
export const IntegrationsSection: Story = { args: { ...base, selectedPath: 'cfg:integrations' } }
export const AnIntegration: Story = { args: { ...base, selectedPath: 'cfg:integration/slack' } }
export const TriggersSection: Story = { args: { ...base, selectedPath: 'cfg:triggers' } }
// One story per trigger type so all auth + "how to use" variants are visible.
export const TheWebhookTrigger: Story = { args: { ...base, selectedPath: 'cfg:trigger/0' } }
export const TheSlackTrigger: Story = { args: { ...base, selectedPath: 'cfg:trigger/1' } }
export const TheChatTrigger: Story = { args: { ...base, selectedPath: 'cfg:trigger/2' } }
export const TheMcpTrigger: Story = { args: { ...base, selectedPath: 'cfg:trigger/3' } }
export const TheCronTrigger: Story = { args: { ...base, selectedPath: 'cfg:trigger/4' } }
export const TheWebhookSecret: Story = { args: { ...base, selectedPath: 'cfg:secret/WEBHOOK_SECRET' } }

/* ── Shell stories — how it composes in the real host ───────────────
 *
 * The explorer is "the whole body"; the only thing above it is the
 * revision dropdown + lifecycle actions (`RevisionBar`). These stories
 * show that composition — first on its own (the configuration tab), then
 * inside the full agent shell chrome (header + tab strip).
 */

// A revision set whose live revision carries the rich SRE spec, so the bar
// and the explorer below it tell one coherent story.
const sreAgent = { ...weeklyDigest, name: 'SRE Slack bot', slug: 'sre-slack-bot' }
const sreRevisions = weeklyDigestRevisions.map((r) => (r.id === sreAgent.live_revision ? { ...r, spec } : r))

/** The configuration body: thin revision bar above the explorer. */
function ConfigBody(): React.ReactElement {
    const [revisionId, setRevisionId] = useState<string | null>(sreAgent.live_revision)
    const [node, setNode] = useState<string | null>(null)
    return (
        <div className="flex h-full min-h-0 flex-col gap-3">
            <RevisionBar
                agent={sreAgent}
                revisions={sreRevisions}
                selectedRevisionId={revisionId}
                onSelectRevision={setRevisionId}
                // eslint-disable-next-line no-console
                onAction={(action, rev) => console.info(`[story] ${action} revision ${rev.id}`)}
                // eslint-disable-next-line no-console
                onTryDraft={(id) => console.info(`[story] try draft ${id}`)}
            />
            <div className="min-h-0 flex-1">
                <AgentConfigExplorer {...base} selectedPath={node} onSelectPath={setNode} height="100%" />
            </div>
        </div>
    )
}

export const InRevisionShell: Story = {
    render: () => (
        <div className="mx-auto h-full max-w-5xl px-6 py-4">
            <ConfigBody />
        </div>
    ),
}

const SHELL_TABS = ['Overview', 'Configuration', 'Sessions', 'Approvals', 'Memory']

export const InFullShell: Story = {
    render: () => (
        <div className="flex h-full min-h-0 flex-col">
            <div className="mx-auto w-full max-w-5xl shrink-0 px-6 pt-6">
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                    <span className="hover:text-foreground">Agents</span>
                    <span>›</span>
                    <span className="text-foreground">{sreAgent.name}</span>
                </div>
                <header className="mt-3 flex items-start justify-between gap-4">
                    <div className="min-w-0 space-y-1">
                        <h1 className="text-xl font-medium tracking-tight">{sreAgent.name}</h1>
                        <p className="text-sm text-muted-foreground">
                            Reacts to alerts in Slack and posts a hypothesis.
                        </p>
                    </div>
                </header>
            </div>
            <div className="mt-5 border-b border-border">
                <div className="mx-auto w-full max-w-5xl px-6">
                    <div className="flex gap-4">
                        {SHELL_TABS.map((t) => (
                            <span
                                key={t}
                                className={
                                    'border-b-2 py-2 text-sm ' +
                                    (t === 'Configuration'
                                        ? 'border-foreground font-medium text-foreground'
                                        : 'border-transparent text-muted-foreground')
                                }
                            >
                                {t}
                            </span>
                        ))}
                    </div>
                </div>
            </div>
            <div className="mx-auto min-h-0 w-full max-w-5xl flex-1 px-6 pb-6 pt-4">
                <ConfigBody />
            </div>
        </div>
    ),
}
