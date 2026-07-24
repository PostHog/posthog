import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { workflowLogic } from '../../../workflowLogic'
import { actionTemplatesLogic } from '../../actionTemplatesLogic'
import { StepFunctionNode } from '../hogFunctionStepLogic'

// The masked shape a linked template's inputs come back as — real values for plain inputs,
// { secret: true } markers for secrets. Copied verbatim into the action config on detach so the
// backend can materialize the secrets server-side.
type MaskedInputs = Record<string, { value?: unknown; secret?: boolean }>

function renderInputValue(input: { value?: unknown; secret?: boolean } | undefined): string {
    if (input?.secret) {
        return '••••••••'
    }
    const value = input?.value
    if (value === undefined || value === null || value === '') {
        return '—'
    }
    return typeof value === 'string' ? value : JSON.stringify(value)
}

export function StartFromTemplateSelector({ node }: { node: StepFunctionNode }): JSX.Element | null {
    const { actionTemplatesByCatalogId } = useValues(actionTemplatesLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const templateId = node.data.config.template_id
    const candidates = actionTemplatesByCatalogId[templateId] ?? []
    const hasInputs = Object.keys(node.data.config.inputs ?? {}).length > 0

    if (candidates.length === 0) {
        return null
    }

    const link = (id: string): void => {
        partialSetWorkflowActionConfig(node.id, {
            action_template_id: id,
            detached_action_template_id: undefined,
            inputs: {},
            mappings: undefined,
        })
    }

    return (
        <LemonField.Pure
            label="Start from a saved template"
            info="Link this step to a reusable template so its configuration stays in sync everywhere it's used."
        >
            <LemonSelect
                placeholder="Choose a saved template…"
                value={null}
                options={candidates.map((t) => ({ value: t.id, label: t.name }))}
                onChange={(id) => {
                    if (!id) {
                        return
                    }
                    if (hasInputs) {
                        LemonDialog.open({
                            title: 'Replace this step with a saved template?',
                            description:
                                'The current configuration on this step will be replaced by the saved template. You can customize it again later.',
                            primaryButton: { children: 'Use template', onClick: () => link(id) },
                            secondaryButton: { children: 'Cancel' },
                        })
                    } else {
                        link(id)
                    }
                }}
            />
        </LemonField.Pure>
    )
}

export function LinkedActionTemplate({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionTemplatesById } = useValues(actionTemplatesLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const actionTemplateId = node.data.config.action_template_id ?? undefined
    const template = actionTemplateId ? actionTemplatesById[actionTemplateId] : undefined

    if (!template) {
        return (
            <LemonBanner type="warning">
                This step is linked to a saved template that no longer exists. Customize it to configure the step
                directly.
                <div className="mt-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() =>
                            partialSetWorkflowActionConfig(node.id, {
                                action_template_id: undefined,
                                detached_action_template_id: actionTemplateId,
                            })
                        }
                    >
                        Customize
                    </LemonButton>
                </div>
            </LemonBanner>
        )
    }

    const maskedInputs = (template.inputs ?? {}) as MaskedInputs

    const detach = (): void => {
        LemonDialog.open({
            title: `Customize this step?`,
            description: `This step will stop receiving updates from "${template.name}". You can change its configuration directly afterwards.`,
            primaryButton: {
                children: 'Customize',
                onClick: () =>
                    partialSetWorkflowActionConfig(node.id, {
                        action_template_id: undefined,
                        detached_action_template_id: template.id,
                        // Copy the template's (masked) inputs inline — the backend resolves the
                        // { secret: true } markers back to real values on save.
                        inputs: maskedInputs as any,
                        mappings: (template.mappings ?? undefined) as any,
                    }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonBanner type="info">
                Linked to saved template <strong>{template.name}</strong>. Changes to the template apply here
                automatically. <Link to={urls.workflows('library')}>Edit saved template</Link>
            </LemonBanner>
            <LemonField.Pure label="Configuration">
                <div className="border rounded p-2 flex flex-col gap-1 bg-surface-secondary">
                    {Object.keys(maskedInputs).length === 0 ? (
                        <span className="italic text-secondary">This template has no configured inputs.</span>
                    ) : (
                        Object.entries(maskedInputs).map(([key, input]) => (
                            <div key={key} className="flex gap-2 text-sm">
                                <span className="font-medium min-w-[8rem]">{key}</span>
                                <span className="text-secondary truncate">{renderInputValue(input)}</span>
                            </div>
                        ))
                    )}
                </div>
            </LemonField.Pure>
            <div>
                <LemonButton type="secondary" size="small" onClick={detach}>
                    Customize
                </LemonButton>
            </div>
        </div>
    )
}

export function SaveAsTemplateButton({ node }: { node: StepFunctionNode }): JSX.Element {
    const { createActionTemplate } = useActions(actionTemplatesLogic)
    const { actionTemplatesLoading } = useValues(actionTemplatesLogic)
    const [isOpen, setIsOpen] = useState(false)
    const [name, setName] = useState('')
    const [description, setDescription] = useState('')

    const open = (): void => {
        setName('')
        setDescription('')
        setIsOpen(true)
    }

    const save = (): void => {
        // Strip compiled fields (bytecode/order) — the server recompiles from value.
        const inputs = Object.fromEntries(
            Object.entries(node.data.config.inputs ?? {}).map(([key, input]) => [
                key,
                { value: (input as any)?.value, secret: (input as any)?.secret },
            ])
        )
        createActionTemplate({
            name,
            description,
            template_id: node.data.config.template_id,
            inputs: inputs as any,
            mappings: ('mappings' in node.data.config ? node.data.config.mappings : undefined) as any,
        })
        setIsOpen(false)
    }

    return (
        <>
            <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={open}>
                Save as template
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Save as action template"
                description="Save this step’s configuration as a reusable template your team can link from any workflow."
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setIsOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={save}
                            loading={actionTemplatesLoading}
                            disabledReason={!name ? 'A name is required' : undefined}
                        >
                            Save template
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-2 min-w-[25rem]">
                    <LemonField.Pure label="Name">
                        <LemonInput
                            autoFocus
                            value={name}
                            placeholder="e.g. Notify billing webhook"
                            onChange={setName}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Description">
                        <LemonTextArea
                            value={description}
                            placeholder="What is this template for?"
                            onChange={setDescription}
                        />
                    </LemonField.Pure>
                </div>
            </LemonModal>
        </>
    )
}
