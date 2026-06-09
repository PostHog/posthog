import { JSX, useMemo } from 'react'

import { IconCheck, IconList, IconWarning, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { PendingPermission, PermissionOption } from '../conversation/acp-types'
import { MarkdownMessage } from '../conversation/primitives/MarkdownMessage'

function isReject(option: PermissionOption): boolean {
    return option.kind === 'reject_once' || option.kind === 'reject_always'
}

function extractPlan(permission: PendingPermission): string | null {
    const rawPlan = (permission.toolCall.rawInput as { plan?: string } | undefined)?.plan
    if (rawPlan) {
        return rawPlan
    }
    const textContent = permission.toolCall.content?.find((c) => c.type === 'content')
    if (textContent && 'content' in textContent) {
        const inner = textContent.content as { type?: string; text?: string } | undefined
        if (inner?.type === 'text' && inner.text) {
            return inner.text
        }
    }
    return null
}

export function PermissionRequestView({
    permission,
    onRespond,
    disabled,
}: {
    permission: PendingPermission
    onRespond: (optionId: string, customInput?: string) => void
    disabled?: boolean
}): JSX.Element {
    const plan = useMemo(() => extractPlan(permission), [permission])
    const isPlan = permission.toolCall.kind === 'plan' || !!plan

    return (
        <div className="mx-auto max-w-4xl rounded-lg border-2 border-accent bg-accent-highlight p-3">
            <div className="mb-2 flex items-center gap-2">
                {isPlan ? <IconList className="text-accent" /> : <IconWarning className="text-warning" />}
                <span className="text-sm font-semibold">{permission.toolCall.title || 'Permission required'}</span>
            </div>

            {plan && (
                <div className="mb-3 max-h-[40vh] overflow-y-auto rounded border border-border bg-bg-light p-3">
                    <MarkdownMessage content={plan} />
                </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
                {permission.options.map((option) => (
                    <LemonButton
                        key={option.optionId}
                        type={isReject(option) ? 'secondary' : 'primary'}
                        status={isReject(option) ? 'danger' : 'default'}
                        size="small"
                        icon={isReject(option) ? <IconX /> : <IconCheck />}
                        disabled={disabled}
                        onClick={() => onRespond(option.optionId)}
                    >
                        {option.name}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
