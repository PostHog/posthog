/**
 * `<ApplicationSettings />` — small card at the top of the Configuration
 * tab covering app-level concerns that live OUTSIDE any revision.
 *
 * Slim by design — the secrets / integrations / mcps that used to live
 * here moved to the dedicated `<ConnectionsTab>` (wiring is its own
 * mental model). What's left is pure provenance + lifecycle status.
 */

import { ArchiveIcon, UserIcon } from 'lucide-react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

export interface ApplicationSettingsProps {
    agent: AgentApplicationFixture
    /** Reserved for future use (e.g. live-revision-derived status hints). */
    referenceRevision?: AgentRevisionFixture | null
}

export function ApplicationSettings({ agent }: ApplicationSettingsProps): React.ReactElement {
    return (
        <div className="grid grid-cols-1 gap-0 divide-y divide-border overflow-hidden rounded-md border border-border bg-card sm:grid-cols-2 sm:divide-x sm:divide-y-0">
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

function formatDate(iso: string): string {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium' })
}
