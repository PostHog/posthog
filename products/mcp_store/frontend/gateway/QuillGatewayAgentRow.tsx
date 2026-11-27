import { IconChevronRight, IconSparkles } from '@posthog/icons'
import { Card, Switch, Text } from '@posthog/quill'

import { MCPServiceAccountApi } from '../generated/api.schemas'

export function QuillGatewayAgentRow({
    account,
    serverCount,
    toolCount,
    statusLoading,
    onOpen,
    onToggleStatus,
}: {
    account: MCPServiceAccountApi
    serverCount: number
    toolCount: number
    statusLoading: boolean
    onOpen: () => void
    onToggleStatus: (checked: boolean) => void
}): JSX.Element {
    const active = account.status === 'active'

    return (
        <Card size="sm" className="p-0">
            <div className="flex flex-wrap items-center gap-2 pr-3">
                <button
                    type="button"
                    className="flex min-w-48 flex-1 items-center gap-3 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={onOpen}
                >
                    <span data-quill className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted">
                        <IconSparkles />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <Text size="sm" weight="medium" className="m-0 truncate" render={<span />}>
                            {account.name}
                        </Text>
                        <Text size="xs" variant="muted" className="m-0" render={<span />}>
                            {`${serverCount} server${serverCount === 1 ? '' : 's'} · ${toolCount} tool${toolCount === 1 ? '' : 's'}`}
                        </Text>
                    </span>
                    <IconChevronRight className="shrink-0 text-muted-foreground" aria-hidden />
                </button>
                <div className="flex flex-col items-end gap-1">
                    <Switch
                        checked={active}
                        aria-label={`${active ? 'Pause' : 'Resume'} ${account.name}`}
                        disabledReason={statusLoading ? 'Saving your change' : undefined}
                        onCheckedChange={onToggleStatus}
                    />
                    {!active && (
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            Paused. All access is off.
                        </Text>
                    )}
                </div>
            </div>
        </Card>
    )
}
