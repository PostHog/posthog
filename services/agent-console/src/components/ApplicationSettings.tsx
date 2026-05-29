/**
 * `<ApplicationSettings />` — small card at the top of the Configuration
 * tab covering app-level concerns that live OUTSIDE any revision.
 *
 * What's app-level (not revision-level):
 *  - `archived` — soft-delete state of the AgentApplication.
 *  - `encrypted_env` — the actual secret VALUES (names live in spec).
 *  - `created_by` / `created_at` — provenance.
 *
 * v0 renders read-only summaries. v0.1+ adds the secrets punch-out
 * link and the archive/restore action (see
 * [`agent-authoring-flow.md`](docs/agent-platform/plans/agent-authoring-flow.md)
 * for the punch-out shape).
 */

import { ArchiveIcon, KeyIcon, UserIcon } from 'lucide-react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

export interface ApplicationSettingsProps {
    agent: AgentApplicationFixture
    /**
     * The live revision (or most recent), used to count declared secrets.
     * Secret VALUES live on the application; their NAMES live on the spec.
     */
    referenceRevision: AgentRevisionFixture | null
}

export function ApplicationSettings({ agent, referenceRevision }: ApplicationSettingsProps): React.ReactElement {
    const spec = (referenceRevision?.spec ?? {}) as Record<string, unknown>
    const declaredSecrets = Array.isArray(spec.secrets) ? (spec.secrets as string[]) : []

    return (
        <div className="grid grid-cols-1 gap-0 divide-y divide-border overflow-hidden rounded-md border border-border bg-card sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            <SettingRow icon={<KeyIcon className="h-3 w-3" />} label="Secrets">
                <SecretsValue declared={declaredSecrets.length} />
            </SettingRow>
            <SettingRow icon={<UserIcon className="h-3 w-3" />} label="Created">
                <span className="font-mono text-[0.6875rem]">{agent.created_by.first_name}</span>
                <span className="text-muted-foreground/70"> · {formatDate(agent.created_at)}</span>
            </SettingRow>
            <SettingRow icon={<ArchiveIcon className="h-3 w-3" />} label="Status">
                {agent.archived ? (
                    <span className="text-warning-foreground">
                        Archived · {formatDate(agent.archived_at ?? agent.updated_at)}
                    </span>
                ) : (
                    <span>Active</span>
                )}
            </SettingRow>
        </div>
    )
}

function SettingRow({
    icon,
    label,
    children,
}: {
    icon: React.ReactNode
    label: string
    children: React.ReactNode
}): React.ReactElement {
    return (
        <div className="flex items-center gap-3 px-3 py-2.5 text-xs">
            <div className="flex items-center gap-1.5 text-muted-foreground">
                {icon}
                <span className="text-[0.6875rem] uppercase tracking-wide">{label}</span>
            </div>
            <div className="ml-auto truncate text-right">{children}</div>
        </div>
    )
}

function SecretsValue({ declared }: { declared: number }): React.ReactElement {
    if (declared === 0) {
        return <span className="text-muted-foreground">None declared</span>
    }
    // v0.1+: surface set/unset counts once the punch-out endpoint lands.
    return (
        <span>
            <span className="font-mono tabular-nums">{declared}</span> declared
        </span>
    )
}

function formatDate(iso: string): string {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium' })
}
