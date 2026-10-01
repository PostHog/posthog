import { useActions, useValues } from 'kea'

import { Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { spaceLoopsLogic } from './spaceLoopsLogic'
import { SpaceLoopTemplateCard } from './SpaceLoopTemplateCard'
import { SPACE_LOOP_TEMPLATE_CATEGORIES, SPACE_LOOP_TEMPLATES, SpaceLoopTemplateCategory } from './spaceLoopTemplates'

export function SpaceLoopTemplates({ id }: { id: string }): JSX.Element {
    const { templateCategory } = useValues(spaceLoopsLogic({ id }))
    const { setTemplateCategory, applyTemplate } = useActions(spaceLoopsLogic({ id }))

    return (
        <section className="flex flex-col gap-3" aria-label="Loop templates">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text render={<h3 />} size="xs" weight="medium" variant="muted" className="uppercase tracking-wide">
                    Start from a template
                </Text>
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
            </div>
            <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-2">
                {SPACE_LOOP_TEMPLATES.filter((template) => template.category === templateCategory).map((template) => (
                    <SpaceLoopTemplateCard
                        key={template.id}
                        template={template}
                        onSelect={() => applyTemplate(template)}
                    />
                ))}
            </div>
        </section>
    )
}
