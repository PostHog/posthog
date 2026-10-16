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
    const mode: RepositoryInputMode = isTemplatedRepository(value) ? 'template' : 'pick'
    // Each mode keeps its last value, so looking at the other mode never loses the author's choice.
    const [lastTemplate, setLastTemplate] = useState<TemplatedRepository>(
        isTemplatedRepository(value) ? value : EMPTY_TEMPLATED_REPOSITORY
    )
    const [lastPick, setLastPick] = useState<string | null>(typeof value === 'string' ? value : null)

    const onModeChange = (nextMode: RepositoryInputMode): void => {
        if (nextMode === mode) {
            return
        }
        if (nextMode === 'pick') {
            if (isTemplatedRepository(value)) {
                setLastTemplate(value)
            }
            onChange(lastPick)
        } else {
            setLastPick(typeof value === 'string' ? value : null)
            onChange(lastTemplate)
        }
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
                    value={value}
                    onChange={onChange}
                    globals={sampleGlobalsWithInputs ?? undefined}
                />
            )}
        </div>
    )
}
