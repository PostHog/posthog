import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { SpaceSettingsSection } from '../SpaceSettingsSection'
import { spaceLoopsLogic } from './spaceLoopsLogic'
import { SpaceLoopTemplateCard } from './SpaceLoopTemplateCard'
import {
    SPACE_LOOP_TEMPLATE_CATEGORIES,
    SPACE_LOOP_TEMPLATES,
    SpaceLoopTemplateCategory,
} from './spaceLoopTemplateCatalog'

export function SpaceLoopTemplates({ id }: { id: string }): JSX.Element {
    const { templateCategory } = useValues(spaceLoopsLogic({ id }))
    const { setTemplateCategory, applyTemplate } = useActions(spaceLoopsLogic({ id }))

    return (
        <SpaceSettingsSection
            label="Start from a template"
            description="A template opens a new loop with its settings filled in. You can change them before you save."
            action={
                <ToggleGroup
                    value={[templateCategory]}
                    onValueChange={(next) => {
                        const [picked] = next
                        if (picked) {
                            setTemplateCategory(picked as SpaceLoopTemplateCategory)
                        }
                    }}
                    aria-label="Template category"
                >
                    {SPACE_LOOP_TEMPLATE_CATEGORIES.map(({ value, label }) => (
                        <ToggleGroupItem
                            key={value}
                            value={value}
                            size="sm"
                            data-attr={`today-space-loop-template-category-${value}`}
                        >
                            {label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            }
        >
            <div className="@container">
                <div className="grid grid-cols-1 gap-2 @xl:grid-cols-2">
                    {SPACE_LOOP_TEMPLATES.filter((template) => template.category === templateCategory).map(
                        (template) => (
                            <SpaceLoopTemplateCard
                                key={template.id}
                                template={template}
                                onSelect={() => applyTemplate(template)}
                            />
                        )
                    )}
                </div>
            </div>
        </SpaceSettingsSection>
    )
}
