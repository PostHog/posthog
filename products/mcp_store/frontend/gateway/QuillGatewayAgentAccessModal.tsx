import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Spinner,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { isPolicyStateAllowedByCeiling, defaultAgentGrantPolicy } from './gatewayPolicyUtils'
import {
    AGENT_POLICY_OPTIONS,
    setAllAgentToolsDisabledReason,
    shareAgentAccessDisabledReason,
} from './GatewayServerAccess'
import { gatewayServerLogic } from './gatewayServerLogic'
import { AGENT_GRANT_SCOPE_OPTIONS } from './gatewayUtils'
import { agentServerAccessKey } from './mcpGatewayLogic'

export function QuillGatewayAgentAccessModal(): JSX.Element | null {
    const {
        agentAccessModalOpen,
        agentAccessPolicyMap,
        agentAccessScope,
        agentAccessSelectedId,
        agentShareDisabledReason,
        agentServerAccessLoadingKeys,
        availableAgentAccounts,
        server,
        teamToolPolicies,
        teamToolPoliciesLoadFailed,
        teamToolPoliciesLoading,
    } = useValues(gatewayServerLogic)
    const {
        closeAgentAccessModal,
        loadTeamToolPolicies,
        setAgentAccessScope,
        setAgentAccessSelectedId,
        setAgentAccessToolPolicy,
        setAllAgentAccessTools,
        submitAgentAccess,
    } = useActions(gatewayServerLogic)

    if (!agentAccessModalOpen || !server) {
        return null
    }

    const submitting = agentAccessSelectedId
        ? agentServerAccessLoadingKeys.has(agentServerAccessKey(agentAccessSelectedId, server.id))
        : false
    const agentOptions = availableAgentAccounts.map((account) => ({
        value: account.id,
        label: `${account.name} (${account.handle})${account.status === 'paused' ? ' (paused)' : ''}`,
    }))

    return (
        <Dialog
            open
            onOpenChange={(open: boolean) => {
                if (!open && !submitting) {
                    closeAgentAccessModal()
                }
            }}
        >
            <DialogContent className="max-w-170">
                <DialogHeader>
                    <DialogTitle>{`Share ${server.name} with an agent`}</DialogTitle>
                    <DialogDescription>
                        Choose an agent and set its tool access. Agents cannot respond to approval prompts.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Select
                            value={agentAccessSelectedId}
                            onValueChange={(next) => setAgentAccessSelectedId(next as string | null)}
                        >
                            <SelectTrigger aria-label="Agent" className="w-full">
                                <SelectValue placeholder="Choose an agent">
                                    {(selected: string | null) =>
                                        agentOptions.find((option) => option.value === selected)?.label ??
                                        'Choose an agent'
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {agentOptions.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>

                        {agentAccessSelectedId && (
                            <>
                                <Field orientation="horizontal" className="flex-wrap">
                                    <FieldContent>
                                        <FieldTitle>Share with</FieldTitle>
                                        <FieldDescription>
                                            A team share lets the agent use your connection for every run in this
                                            project.
                                        </FieldDescription>
                                    </FieldContent>
                                    <ToggleGroup
                                        aria-label="Share with"
                                        value={[agentAccessScope]}
                                        onValueChange={(next: string[]) => {
                                            const picked = AGENT_GRANT_SCOPE_OPTIONS.find(
                                                (option) => option.value === next[0]
                                            )

                                            if (picked) {
                                                setAgentAccessScope(picked.value)
                                            }
                                        }}
                                    >
                                        {AGENT_GRANT_SCOPE_OPTIONS.map((option) => (
                                            <Tooltip key={option.value}>
                                                <TooltipTrigger render={<ToggleGroupItem value={option.value} />}>
                                                    {option.label}
                                                </TooltipTrigger>
                                                <TooltipContent>{option.tooltip}</TooltipContent>
                                            </Tooltip>
                                        ))}
                                    </ToggleGroup>
                                </Field>

                                <Field orientation="horizontal" className="flex-wrap">
                                    <FieldContent>
                                        <FieldTitle>Tool access</FieldTitle>
                                        <FieldDescription>
                                            Destructive tools start blocked. Other tools start allowed.
                                        </FieldDescription>
                                    </FieldContent>
                                    <div className="flex flex-wrap items-center gap-1">
                                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                            Set all
                                        </Text>
                                        {AGENT_POLICY_OPTIONS.map((option) => (
                                            <Button
                                                key={option.value}
                                                onClick={() => setAllAgentAccessTools(option.value)}
                                                disabledReason={setAllAgentToolsDisabledReason({
                                                    state: option.value,
                                                    teamToolPolicies,
                                                    teamToolPoliciesLoading,
                                                    teamToolPoliciesLoadFailed,
                                                })}
                                            >
                                                {option.label}
                                            </Button>
                                        ))}
                                    </div>
                                </Field>

                                {teamToolPoliciesLoading ? (
                                    <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4">
                                        <Spinner />
                                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                            Loading tools…
                                        </Text>
                                    </div>
                                ) : teamToolPoliciesLoadFailed ? (
                                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed border-border p-4">
                                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                            Couldn’t load this server’s tools. Try again before sharing access.
                                        </Text>
                                        <Button variant="outline" onClick={() => loadTeamToolPolicies()}>
                                            Retry
                                        </Button>
                                    </div>
                                ) : teamToolPolicies.length === 0 ? (
                                    <div className="rounded-md border border-dashed border-border p-4">
                                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                            No tools have been discovered for this server yet.
                                        </Text>
                                    </div>
                                ) : (
                                    <div className="max-h-80 divide-y divide-border overflow-y-auto rounded-md border border-border">
                                        {teamToolPolicies.map((policy) => {
                                            const ruleLocked = policy.decided_by === 'rule'
                                            const value =
                                                agentAccessPolicyMap[policy.tool_name] ??
                                                defaultAgentGrantPolicy(
                                                    policy.tool_name,
                                                    policy.team_state,
                                                    policy.is_destructive
                                                )

                                            return (
                                                <div
                                                    key={policy.tool_name}
                                                    className="flex flex-wrap items-center gap-3 p-3"
                                                >
                                                    <div className="flex min-w-48 flex-1 flex-col gap-0.5">
                                                        <Text
                                                            size="xs"
                                                            render={<span className="m-0 truncate font-mono" />}
                                                        >
                                                            {policy.tool_name}
                                                        </Text>
                                                        <Text
                                                            size="xs"
                                                            variant="muted"
                                                            render={<span className="m-0 truncate" />}
                                                        >
                                                            {policy.description || 'No description provided'}
                                                        </Text>
                                                    </div>
                                                    {ruleLocked ? (
                                                        <Badge>
                                                            {policy.policy_state === 'approved'
                                                                ? 'Allowed by rule'
                                                                : 'Blocked by rule'}
                                                        </Badge>
                                                    ) : (
                                                        <ToggleGroup
                                                            size="sm"
                                                            aria-label={`Access to ${policy.tool_name}`}
                                                            value={[value]}
                                                            onValueChange={(next: string[]) => {
                                                                const picked = AGENT_POLICY_OPTIONS.find(
                                                                    (option) => option.value === next[0]
                                                                )

                                                                if (picked) {
                                                                    setAgentAccessToolPolicy(
                                                                        policy.tool_name,
                                                                        picked.value
                                                                    )
                                                                }
                                                            }}
                                                        >
                                                            {AGENT_POLICY_OPTIONS.map((option) => (
                                                                <ToggleGroupItem
                                                                    key={option.value}
                                                                    value={option.value}
                                                                    disabledReason={
                                                                        isPolicyStateAllowedByCeiling(
                                                                            option.value,
                                                                            policy.team_state
                                                                        )
                                                                            ? undefined
                                                                            : 'Unavailable because of the team policy'
                                                                    }
                                                                >
                                                                    {option.label}
                                                                </ToggleGroupItem>
                                                            ))}
                                                        </ToggleGroup>
                                                    )}
                                                </div>
                                            )
                                        })}
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeAgentAccessModal}
                        disabledReason={submitting ? 'Sharing access' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={submitAgentAccess}
                        loading={submitting}
                        disabledReason={shareAgentAccessDisabledReason({
                            agentShareDisabledReason,
                            agentAccessSelectedId,
                            teamToolPoliciesLoading,
                            teamToolPoliciesLoadFailed,
                            availableAgentCount: availableAgentAccounts.length,
                        })}
                    >
                        Share access
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
