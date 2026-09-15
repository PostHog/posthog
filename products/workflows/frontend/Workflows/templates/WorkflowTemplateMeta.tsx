import { IconBolt, IconClock, IconPeople } from '@posthog/icons'

import type { HogFlowTemplate } from '../hogflows/types'
import { getTemplateScopeLabel, getTemplateTrigger } from './workflowTemplateDisplay'

/** The facts under a template's description: how it starts, and who it belongs to. */
export function WorkflowTemplateMeta({ template }: { template: HogFlowTemplate }): JSX.Element | null {
    const trigger = getTemplateTrigger(template)
    const scopeLabel = getTemplateScopeLabel(template.scope)

    if (!trigger && !scopeLabel) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-accent">
            {trigger && (
                <MetaFact icon={trigger.type === 'schedule' ? <IconClock /> : <IconBolt />} label={trigger.label} />
            )}
            {scopeLabel && <MetaFact icon={<IconPeople />} label={`${scopeLabel} template`} />}
        </div>
    )
}

function MetaFact({ icon, label }: { icon: JSX.Element; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1 min-w-0">
            <span className="shrink-0">{icon}</span>
            <span className="truncate">{label}</span>
        </span>
    )
}
