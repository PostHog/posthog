import { useActions, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Spinner,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { PolicyScope, gatewayServerLogic, TOOL_PREVIEW_LIMIT } from './gatewayServerLogic'
import { bulkPolicyDisabledReason } from './GatewayServerScene'
import { POLICY_OPTIONS } from './gatewayUtils'
import { mcpGatewayLogic } from './mcpGatewayLogic'
import { QuillPolicySummary } from './QuillPolicySummary'
import { QuillToolPolicyRow } from './QuillToolPolicyRow'

function scopeKey(candidate: PolicyScope): string | number {
    return candidate.scopeServiceAccountId ?? candidate.scopeUserId ?? candidate.scopeType
}

export function QuillToolPoliciesSection(): JSX.Element {
    const {
        availableScopes,
        canEditScope,
        displayedToolPolicies,
        filteredToolPolicies,
        isAdmin,
        canManageAgentAccess,
        policyCounts,
        refreshInstallationId,
        refreshingInstallationIds,
        scope,
        scopeIsResolving,
        toolPolicies,
        toolPoliciesLoading,
        toolPolicyGroups,
        toolSearch,
        toolsExpanded,
    } = useValues(gatewayServerLogic)
    const { setScope, setAllTools, setToolSearch, toggleToolsExpanded } = useActions(gatewayServerLogic)
    const { refreshServerTools } = useActions(mcpGatewayLogic)
    const agentScope = scope.scopeType === 'agent'
    const bulkOptions = agentScope
        ? POLICY_OPTIONS.filter((option) => option.value !== 'needs_approval')
        : POLICY_OPTIONS

    if (scopeIsResolving) {
        return (
            <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4">
                <Spinner />
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Loading agent tool policies…
                </Text>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Tools
                    </Heading>
                    <Badge>{toolPolicies.length}</Badge>
                    <QuillPolicySummary counts={policyCounts} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {canEditScope && (
                        <div className="flex items-center gap-1">
                            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                {toolSearch.trim() ? 'Set filtered' : 'Set all'}
                            </Text>
                            {bulkOptions.map((option) => (
                                <Button
                                    key={option.value}
                                    size="icon"
                                    aria-label={option.label}
                                    tooltip={option.label}
                                    loading={toolPoliciesLoading}
                                    disabledReason={bulkPolicyDisabledReason(option.value, filteredToolPolicies, scope)}
                                    onClick={() => setAllTools({ state: option.value })}
                                >
                                    {option.icon}
                                </Button>
                            ))}
                        </div>
                    )}
                    {refreshInstallationId && (
                        <Button
                            variant="outline"
                            size="icon"
                            tooltip="Refresh tools from server"
                            aria-label="Refresh tools from server"
                            loading={refreshingInstallationIds.has(refreshInstallationId)}
                            onClick={() => refreshServerTools(refreshInstallationId)}
                        >
                            <IconRefresh />
                        </Button>
                    )}
                </div>
            </div>

            {(isAdmin || canManageAgentAccess) && availableScopes.length > 1 && (
                <div
                    data-quill
                    className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted p-2"
                >
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        Policy for
                    </Text>
                    <ToggleGroup
                        size="sm"
                        aria-label="Policy for"
                        className="flex-wrap"
                        value={[String(scopeKey(scope))]}
                        onValueChange={(next: string[]) => {
                            const picked = availableScopes.find((candidate) => String(scopeKey(candidate)) === next[0])

                            if (picked) {
                                setScope(picked)
                            }
                        }}
                    >
                        {availableScopes.map((candidate) => (
                            <ToggleGroupItem
                                key={String(scopeKey(candidate))}
                                value={String(scopeKey(candidate))}
                                disabledReason={toolPoliciesLoading ? 'Updating tool policies' : undefined}
                            >
                                {candidate.label}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </div>
            )}

            {toolPolicies.length > 5 && (
                <InputGroup size="sm">
                    <InputGroupAddon align="inline-start">
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        placeholder="Search tools…"
                        aria-label="Search tools"
                        value={toolSearch}
                        onChange={(event) => setToolSearch(event.target.value)}
                    />
                </InputGroup>
            )}

            {toolPoliciesLoading && toolPolicies.length === 0 ? (
                <div className="flex justify-center p-6">
                    <Spinner />
                </div>
            ) : toolPolicies.length === 0 ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>No tools discovered yet.</EmptyTitle>
                        <EmptyDescription>
                            {refreshInstallationId
                                ? 'This server listed no tools. Refresh to try again.'
                                : 'Connect your account to list this server’s tools.'}
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : filteredToolPolicies.length === 0 ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyDescription>No tools match “{toolSearch}”.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : toolPolicyGroups ? (
                <div className="flex flex-col gap-2">
                    {toolPolicyGroups.map((group) => (
                        <Collapsible key={group.key} defaultOpen className="rounded-md border border-border">
                            <CollapsibleTrigger className="w-full">
                                {group.label}
                                <Badge>{group.policies.length}</Badge>
                            </CollapsibleTrigger>
                            <CollapsibleContent>
                                <div className="divide-y divide-border border-t border-border">
                                    {group.policies.map((policy) => (
                                        <QuillToolPolicyRow key={policy.tool_name} policy={policy} />
                                    ))}
                                </div>
                            </CollapsibleContent>
                        </Collapsible>
                    ))}
                </div>
            ) : (
                <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
                    {displayedToolPolicies.map((policy) => (
                        <QuillToolPolicyRow key={policy.tool_name} policy={policy} />
                    ))}
                    {filteredToolPolicies.length > TOOL_PREVIEW_LIMIT && !toolSearch.trim() && (
                        <Button className="w-full" onClick={toggleToolsExpanded}>
                            {toolsExpanded
                                ? 'View less'
                                : `View ${filteredToolPolicies.length - TOOL_PREVIEW_LIMIT} more`}
                        </Button>
                    )}
                </div>
            )}
        </div>
    )
}
