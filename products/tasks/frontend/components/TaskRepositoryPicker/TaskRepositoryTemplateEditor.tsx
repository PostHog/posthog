import { LemonSnack } from '@posthog/lemon-ui'

import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'

import { TaskRepositoryCombobox } from './TaskRepositoryCombobox'

export interface TemplatedRepository {
    template: string
    allowed: string[]
}

export function TaskRepositoryTemplateEditor({
    value,
    onChange,
    globals,
}: {
    value: TemplatedRepository
    onChange: (value: TemplatedRepository) => void
    globals?: Record<string, any>
}): JSX.Element {
    const allowed = value.allowed ?? []

    return (
        <div className="flex flex-col gap-2">
            <CodeEditorInline
                className="overflow-hidden"
                minHeight="37"
                value={value.template}
                onChange={(template) => onChange({ ...value, template: template ?? '' })}
                language="hogTemplate"
                globals={globals}
            />
            <div className="flex flex-col gap-1">
                <span className="text-secondary text-xs">
                    Allowed repositories. The step fails when the template renders any other repository.
                </span>
                <div className="flex items-center gap-1 flex-wrap">
                    {allowed.map((repository) => (
                        <LemonSnack
                            key={repository}
                            onClose={() =>
                                onChange({ ...value, allowed: allowed.filter((name) => name !== repository) })
                            }
                            data-attr="task-repository-allowed"
                        >
                            {repository}
                        </LemonSnack>
                    ))}
                    <TaskRepositoryCombobox
                        value=""
                        onChange={(repository) =>
                            repository && !allowed.includes(repository)
                                ? onChange({ ...value, allowed: [...allowed, repository] })
                                : undefined
                        }
                        placeholder="Add repository..."
                        excluded={allowed}
                    />
                </div>
            </div>
        </div>
    )
}
