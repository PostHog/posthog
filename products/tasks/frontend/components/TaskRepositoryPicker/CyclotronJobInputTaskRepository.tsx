import { useState } from 'react'

import { IconBrackets, IconGithub } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { TaskRepositoryCombobox } from './TaskRepositoryCombobox'
import { TaskRepositoryTemplateEditor, TemplatedRepository } from './TaskRepositoryTemplateEditor'

type RepositoryInputMode = 'pick' | 'template'

const EMPTY_TEMPLATED_REPOSITORY: TemplatedRepository = { template: '', allowed: [] }

const isTemplatedRepository = (value: unknown): value is TemplatedRepository =>
    typeof value === 'object' && value !== null && 'template' in value

export default function CyclotronJobInputTaskRepository({
    value,
    onChange,
    sampleGlobalsWithInputs,
}: CustomInputRendererProps): JSX.Element {
    const [mode, setMode] = useState<RepositoryInputMode>(isTemplatedRepository(value) ? 'template' : 'pick')
    // Kept while the author looks at Pick, so switching back does not lose the template.
    const [lastTemplate, setLastTemplate] = useState<TemplatedRepository>(
        isTemplatedRepository(value) ? value : EMPTY_TEMPLATED_REPOSITORY
    )

    const onModeChange = (nextMode: RepositoryInputMode): void => {
        if (nextMode === 'pick' && isTemplatedRepository(value)) {
            setLastTemplate(value)
            onChange(null)
        }
        if (nextMode === 'template') {
            onChange(lastTemplate)
        }
        setMode(nextMode)
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonSelect
                    size="small"
                    value={mode}
                    options={[
                        { value: 'pick', label: 'Pick', icon: <IconGithub /> },
                        { value: 'template', label: 'Template', icon: <IconBrackets /> },
                    ]}
                    onChange={onModeChange}
                    data-attr="task-repository-input-mode"
                />
                {mode === 'pick' && (
                    <TaskRepositoryCombobox
                        value={typeof value === 'string' ? value : ''}
                        onChange={(repository) => onChange(repository)}
                        showNoneOption
                    />
                )}
            </div>
            {mode === 'template' && (
                <TaskRepositoryTemplateEditor
                    value={isTemplatedRepository(value) ? value : lastTemplate}
                    onChange={onChange}
                    globals={sampleGlobalsWithInputs ?? undefined}
                />
            )}
        </div>
    )
}
