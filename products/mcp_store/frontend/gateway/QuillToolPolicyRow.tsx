import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import {
    Badge,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { ResolvedToolPolicyApi } from '../generated/api.schemas'
import { gatewayServerLogic } from './gatewayServerLogic'
import { getToolPolicyDisplay } from './GatewayServerScene'
import { POLICY_OPTIONS } from './gatewayUtils'

export function QuillToolPolicyRow({ policy }: { policy: ResolvedToolPolicyApi }): JSX.Element {
    const { server, scope, canEditScope, toolPoliciesLoading } = useValues(gatewayServerLogic)
    const { setToolPolicy } = useActions(gatewayServerLogic)

    const fqName = `${server?.name ?? ''}.${policy.tool_name}`
    const { ruleLocked, setByTeamAdmin, displayedState, options, rulePolicyLabel } = getToolPolicyDisplay(policy, scope)
    const groupDisabledReason = toolPoliciesLoading
        ? 'Updating tool policies'
        : policy.locked
          ? 'The team policy blocks this tool.'
          : undefined

    const policyControl =
        ruleLocked || !canEditScope ? (
            <Tooltip>
                <TooltipTrigger render={<Badge tabIndex={0} />}>
                    <IconLock />
                    {ruleLocked
                        ? rulePolicyLabel
                        : POLICY_OPTIONS.find((option) => option.value === displayedState)?.label}
                </TooltipTrigger>
                <TooltipContent>
                    {ruleLocked
                        ? `${policy.rule_name}: team rule that overrides every scope.`
                        : 'This policy is read-only.'}
                </TooltipContent>
            </Tooltip>
        ) : (
            <div className="flex flex-wrap items-center gap-2">
                {setByTeamAdmin && (
                    <Tooltip>
                        <TooltipTrigger render={<Badge tabIndex={0} />}>
                            <IconLock />
                            Set by team admin
                        </TooltipTrigger>
                        <TooltipContent>This effective state is limited by the team policy.</TooltipContent>
                    </Tooltip>
                )}
                <ToggleGroup
                    size="sm"
                    aria-label={`Policy for ${fqName}`}
                    value={[displayedState]}
                    onValueChange={(next: string[]) => {
                        const picked = options.find((option) => option.value === next[0])

                        if (picked) {
                            setToolPolicy({ toolName: policy.tool_name, state: picked.value })
                        }
                    }}
                >
                    {options.map((option) => (
                        <ToggleGroupItem
                            key={option.value}
                            value={option.value}
                            disabledReason={groupDisabledReason ?? option.disabledReason}
                        >
                            {option.icon}
                            {option.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
        )

    return (
        <Collapsible className="p-2">
            <CollapsibleHeader className="flex-wrap items-start">
                <CollapsibleTrigger iconOnly>{`Show details for ${fqName}`}</CollapsibleTrigger>
                <div className="flex min-w-48 flex-1 flex-col gap-0.5">
                    <Text
                        size="xs"
                        variant={displayedState === 'do_not_use' ? 'muted' : 'default'}
                        render={
                            <span className={cn('m-0 font-mono', displayedState === 'do_not_use' && 'line-through')} />
                        }
                    >
                        {fqName}
                    </Text>
                    <Text size="xs" variant="muted" render={<span className="m-0 truncate italic" />}>
                        {policy.description || 'No description provided'}
                    </Text>
                </div>
                <div className="shrink-0">{policyControl}</div>
            </CollapsibleHeader>
            <CollapsibleContent>
                <div className="flex flex-col gap-3 pt-2 pl-9">
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="semibold" variant="muted" render={<span className="m-0 uppercase" />}>
                            Description
                        </Text>
                        <Text size="xs" render={<p className="m-0" />}>
                            {policy.description || 'No description provided'}
                        </Text>
                    </div>
                    {ruleLocked && (
                        <div className="flex flex-col gap-1">
                            <Text
                                size="xs"
                                weight="semibold"
                                variant="muted"
                                render={<span className="m-0 uppercase" />}
                            >
                                Applied rule
                            </Text>
                            <Text size="xs" render={<p className="m-0" />}>
                                {policy.rule_name}: {policy.rule_description}
                            </Text>
                        </div>
                    )}
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="semibold" variant="muted" render={<span className="m-0 uppercase" />}>
                            Input schema
                        </Text>
                        <CodeSnippet language={Language.JSON} wrap>
                            {JSON.stringify(policy.input_schema, null, 2)}
                        </CodeSnippet>
                    </div>
                </div>
            </CollapsibleContent>
        </Collapsible>
    )
}
