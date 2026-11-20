import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Heading,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    DataTableProps,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { TZLabel } from 'lib/components/TZLabel'
import { fullName } from 'lib/utils/strings'

import { MCPAuditEventApi } from '../generated/api.schemas'
import { FILTERS, auditCallerName } from './GatewayAuditLog'
import { AUDIT_PAGE_SIZE, AuditQuickFilter, gatewayAuditLogic } from './gatewayAuditLogic'
import { credentialOwnerLabel } from './gatewayUtils'
import { mcpGatewayLogic } from './mcpGatewayLogic'
import { QuillDecisionTag } from './QuillDecisionTag'

const columns: DataTableProps<MCPAuditEventApi, unknown>['columns'] = [
    {
        id: 'created_at',
        header: 'Time',
        cell: ({ row }) => <TZLabel time={row.original.created_at} />,
    },
    {
        id: 'caller',
        header: 'Caller',
        meta: { expand: true },
        cell: ({ row }) => {
            const event = row.original

            return (
                <div className="flex min-w-0 flex-col gap-0.5">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                        {event.actor_service_account ? (
                            <span className="flex min-w-0 items-center gap-1">
                                <IconSparkles />
                                <Text size="xs" className="m-0 truncate" render={<span />}>
                                    {event.actor_service_account.name}
                                </Text>
                            </span>
                        ) : event.actor_user ? (
                            <span className="flex min-w-0 items-center gap-1">
                                <QuillPersonAvatar
                                    name={fullName(event.actor_user) || event.actor_user.email}
                                    email={event.actor_user.email}
                                    size="xs"
                                />
                                <Text size="xs" className="m-0 truncate" render={<span />}>
                                    {fullName(event.actor_user) || event.actor_user.email}
                                </Text>
                            </span>
                        ) : (
                            <Text size="xs" variant="muted" className="m-0 truncate" render={<span />}>
                                {event.actor_label || 'Unknown'}
                            </Text>
                        )}
                        <Badge
                            variant={
                                event.actor_service_account ? 'completed' : event.actor_user ? 'default' : 'warning'
                            }
                        >
                            {event.actor_service_account ? 'Agent' : event.actor_user ? 'Human' : 'Deleted'}
                        </Badge>
                    </div>
                    {event.actor_service_account && event.credential_owner && (
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            {credentialOwnerLabel(event.credential_owner, event.grant_scope)}
                        </Text>
                    )}
                </div>
            )
        },
    },
    {
        id: 'server',
        header: 'MCP server · tool called',
        cell: ({ row }) => (
            <div className="flex flex-col">
                <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                    {row.original.server_name}
                </Text>
                <Text size="xs" variant="muted" className="font-mono" render={<span className="m-0" />}>
                    {`${row.original.tool_name}()`}
                </Text>
            </div>
        ),
    },
    {
        id: 'decision',
        header: 'Decision',
        cell: ({ row }) => <QuillDecisionTag decision={row.original.decision} />,
    },
]

export function QuillGatewayAuditLog(): JSX.Element {
    const { auditResponse, auditResponseLoading, callerFilter, counts, hasActiveFilters, quickFilter, page } =
        useValues(gatewayAuditLogic)
    const { clearFilters, setCallerFilter, setQuickFilter, setPage } = useActions(gatewayAuditLogic)
    const { isAdmin, serviceAccounts } = useValues(mcpGatewayLogic)

    const selectedCallerName = auditCallerName(callerFilter, serviceAccounts)
    const pageCount = Math.max(Math.ceil(auditResponse.count / AUDIT_PAGE_SIZE), 1)
    const matchSuffix = hasActiveFilters
        ? auditResponse.count === 1
            ? ' matches your filters'
            : ' match your filters'
        : ''

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Audit log
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {isAdmin
                        ? 'This log shows every tool call routed through the gateway and how the gateway handled it.'
                        : 'This log shows tool calls made through your MCP server connections, including calls from agents you shared them with.'}
                </Text>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
                <ToggleGroup
                    spacing={2}
                    value={[quickFilter]}
                    onValueChange={(next: string[]) => {
                        const picked = FILTERS.find((filter) => filter.key === next[0])

                        if (picked) {
                            setQuickFilter(picked.key as AuditQuickFilter)
                        }
                    }}
                    className="flex-wrap"
                >
                    {FILTERS.map((filter) => (
                        <ToggleGroupItem key={filter.key} value={filter.key}>
                            {filter.label}
                            {counts && <Badge>{counts[filter.countKey] ?? 0}</Badge>}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                <Select value={callerFilter} onValueChange={(value) => setCallerFilter(value as string)}>
                    <SelectTrigger aria-label="Filter by caller">
                        <SelectValue>{() => `Caller: ${selectedCallerName}`}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">Everyone</SelectItem>
                        {serviceAccounts.length > 0 && (
                            <SelectGroup>
                                <SelectSeparator />
                                <SelectGroupLabel>Agents</SelectGroupLabel>
                                {serviceAccounts.map((account) => (
                                    <SelectItem key={account.id} value={account.id}>
                                        {account.name}
                                    </SelectItem>
                                ))}
                            </SelectGroup>
                        )}
                    </SelectContent>
                </Select>
            </div>

            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    {`${auditResponse.count} tool ${auditResponse.count === 1 ? 'call' : 'calls'}${matchSuffix}`}
                </Text>
                {hasActiveFilters && <Button onClick={clearFilters}>Clear filters</Button>}
            </div>

            {auditResponseLoading && auditResponse.results.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-10" />
                    <Skeleton className="h-10" />
                    <Skeleton className="h-10" />
                </div>
            ) : (
                <div className="flex flex-col gap-2 rounded-md border border-border">
                    <DataTable
                        columns={columns}
                        data={auditResponse.results}
                        fullWidth
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyDescription>
                                        {hasActiveFilters
                                            ? 'No tool calls match these filters. Clear the filters to see more activity.'
                                            : 'No tool calls are available in this audit log yet.'}
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                    {auditResponse.count > AUDIT_PAGE_SIZE && (
                        <QuillTablePagination
                            currentPage={page}
                            pageCount={pageCount}
                            pageSize={AUDIT_PAGE_SIZE}
                            total={auditResponse.count}
                            onPageChange={setPage}
                        />
                    )}
                </div>
            )}
        </div>
    )
}
