import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch, lemonToast } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import {
    CODE_ACCESS_SETTINGS,
    NOTIFICATION_SETTINGS,
    PR_GENERATION_SETTINGS,
    SIGNAL_SOURCE_SETTINGS,
    USAGE_STATS,
} from '../mockData'
import { DemoToggleRow } from '../types'
import { v2InboxLogic } from '../v2InboxLogic'

function SettingsSection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <div className="flex flex-col gap-0.5">
                <h3 className="m-0 text-sm font-semibold">{title}</h3>
                {description ? <p className="m-0 text-xs text-secondary">{description}</p> : null}
            </div>
            {children}
        </div>
    )
}

function ToggleRows({ rows }: { rows: DemoToggleRow[] }): JSX.Element {
    const { toggles } = useValues(v2InboxLogic)
    const { toggleSetting } = useActions(v2InboxLogic)
    return (
        <div className="flex flex-col">
            {rows.map((row) => (
                <div
                    key={row.key}
                    className="flex items-center gap-4 border-b border-primary py-2.5 last:border-b-0 last:pb-0"
                >
                    <div className="flex min-w-0 flex-1 flex-col">
                        <span className="text-sm">{row.label}</span>
                        {row.detail ? <span className="text-xs text-tertiary">{row.detail}</span> : null}
                    </div>
                    <LemonSwitch
                        checked={toggles[row.key]}
                        onChange={() => toggleSetting(row.key)}
                        data-attr={`v2-setting-${row.key.replace(':', '-')}`}
                    />
                </div>
            ))}
        </div>
    )
}

export function InboxSettingsTab(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <SettingsSection title="Signal sources" description="Scouts only read from sources that are turned on.">
                <ToggleRows rows={SIGNAL_SOURCE_SETTINGS} />
            </SettingsSection>

            <SettingsSection title="PR generation" description="How a fix plan becomes a pull request.">
                <ToggleRows rows={PR_GENERATION_SETTINGS} />
            </SettingsSection>

            <SettingsSection title="Code access" description="What the fix agent can read and write.">
                <div className="flex items-center gap-4 border-b border-primary pb-2.5">
                    <div className="flex min-w-0 flex-1 flex-col">
                        <span className="font-mono text-sm">posthog/posthog</span>
                        <span className="text-xs text-tertiary">Read and write through the PostHog GitHub app</span>
                    </div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => lemonToast.info('Not part of this demo')}
                        data-attr="v2-settings-manage-github"
                    >
                        Manage on GitHub
                    </LemonButton>
                </div>
                <ToggleRows rows={CODE_ACCESS_SETTINGS} />
            </SettingsSection>

            <SettingsSection title="Notifications">
                <ToggleRows rows={NOTIFICATION_SETTINGS} />
            </SettingsSection>

            <SettingsSection title="Usage" description="This month so far.">
                <div className="flex flex-col">
                    {USAGE_STATS.map((stat) => (
                        <div
                            key={stat.label}
                            className="flex items-center justify-between gap-4 border-b border-primary py-2 last:border-b-0"
                        >
                            <span className="text-sm">{stat.label}</span>
                            <span className="font-mono text-sm font-semibold">{stat.value}</span>
                        </div>
                    ))}
                </div>
                <div className="flex flex-col gap-1.5">
                    <LemonProgress percent={62} strokeColor="var(--color-accent)" />
                    <span className="text-xs text-tertiary">1,240 of 2,000 included scout runs used</span>
                </div>
            </SettingsSection>
        </div>
    )
}
