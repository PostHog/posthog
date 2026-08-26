import { LemonTag } from '@posthog/lemon-ui'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'

import type { HogFlowTemplate } from '../Workflows/hogflows/types'
import { TemplateCard } from './TemplateCard'

// Matches the wording of the scope picker in the save-as-template modal, so a template reads the
// same where you set it and where you find it again.
const SCOPE_LABELS: Record<string, string> = {
    team: 'This project',
    organization: 'All projects',
}

export function WorkflowTemplateCard({
    template,
    index,
    onClick,
    actions,
}: {
    template: HogFlowTemplate
    index: number
    onClick: () => void
    actions?: React.ReactNode
}): JSX.Element {
    const scopeLabel = template.scope ? SCOPE_LABELS[template.scope] : undefined

    return (
        <TemplateCard
            name={template.name}
            description={template.description}
            createdBy={template.created_by}
            createdAt={template.created_at}
            onClick={onClick}
            actions={actions}
            data-attr="workflow-template-item"
            tags={
                <>
                    <LemonTag type="highlight">Workflow</LemonTag>
                    {scopeLabel && <LemonTag>{scopeLabel}</LemonTag>}
                    {template.tags?.map((tag) => (
                        <LemonTag key={tag}>{tag}</LemonTag>
                    ))}
                </>
            }
            preview={
                <FallbackCoverImage
                    src={template.image_url || undefined}
                    alt="cover photo"
                    index={index}
                    className="h-full"
                />
            }
        />
    )
}
