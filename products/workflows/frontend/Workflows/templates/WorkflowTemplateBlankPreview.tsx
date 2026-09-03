import { IconPlus } from '@posthog/icons'

/** Stands in for the step icons on the "blank workflow" card, which has no steps yet. */
export function WorkflowTemplateBlankPreview(): JSX.Element {
    return (
        <div className="flex items-center justify-center rounded size-6 shrink-0 border border-dashed text-secondary">
            <IconPlus />
        </div>
    )
}
