import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTag, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { CyclotronJobInputType } from '~/types'

import { HogFlowActionTemplateApi, actionTemplatesLogic } from '../Workflows/hogflows/actionTemplatesLogic'
import { actionTemplateEditorLogic } from './actionTemplateEditorLogic'

function ActionTemplateEditorModal({
    actionTemplate,
    onClose,
}: {
    actionTemplate: HogFlowActionTemplateApi
    onClose: () => void
}): JSX.Element {
    const logic = actionTemplateEditorLogic({ actionTemplate })
    const { catalogTemplate, catalogTemplateLoading, name, description, inputs } = useValues(logic)
    const { setName, setDescription, setInput, save } = useActions(logic)
    const { actionTemplatesLoading } = useValues(actionTemplatesLogic)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={`Edit ${actionTemplate.name}`}
            description="Changes apply to every workflow step linked to this template."
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={actionTemplatesLoading}
                        disabledReason={!name ? 'A name is required' : undefined}
                        onClick={() => {
                            save()
                            onClose()
                        }}
                    >
                        Save changes
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <LemonField.Pure label="Name">
                    <LemonInput value={name} onChange={setName} />
                </LemonField.Pure>
                <LemonField.Pure label="Description">
                    <LemonTextArea value={description} onChange={setDescription} />
                </LemonField.Pure>
                <LemonField.Pure label="Configuration">
                    {catalogTemplateLoading ? (
                        <Spinner />
                    ) : catalogTemplate ? (
                        <CyclotronJobInputs
                            configuration={{
                                inputs: inputs as Record<string, CyclotronJobInputType>,
                                inputs_schema: catalogTemplate.inputs_schema ?? [],
                            }}
                            showSource={false}
                            sampleGlobalsWithInputs={null}
                            onInputChange={(key, value) => setInput(key, value)}
                        />
                    ) : (
                        <span className="italic text-secondary">
                            The underlying destination template could not be loaded.
                        </span>
                    )}
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}

export function ActionTemplatesTable(): JSX.Element {
    const { actionTemplates, actionTemplatesLoading } = useValues(actionTemplatesLogic)
    const { deleteActionTemplate } = useActions(actionTemplatesLogic)
    const [editing, setEditing] = useState<HogFlowActionTemplateApi | null>(null)

    return (
        <div className="flex flex-col gap-2" data-attr="action-templates-table">
            <div>
                <h3 className="mb-0">Action templates</h3>
                <p className="text-secondary mb-0">
                    Reusable configurations for webhook and destination steps. Editing one updates every workflow linked
                    to it.
                </p>
            </div>
            <LemonTable
                loading={actionTemplatesLoading}
                dataSource={actionTemplates}
                emptyState="No action templates yet. Configure a function step in a workflow and choose “Save as template”."
                columns={[
                    {
                        title: 'Name',
                        dataIndex: 'name',
                        render: (_, template) => <span className="font-medium">{template.name}</span>,
                    },
                    {
                        title: 'Type',
                        dataIndex: 'template_id',
                        render: (_, template) => <LemonTag type="muted">{template.template_id}</LemonTag>,
                    },
                    {
                        title: 'Used by',
                        dataIndex: 'usage_count',
                        render: (_, template) =>
                            `${template.usage_count} workflow${template.usage_count === 1 ? '' : 's'}`,
                    },
                    {
                        title: 'Last modified',
                        dataIndex: 'updated_at',
                        render: (_, template) => <TZLabel time={template.updated_at} />,
                    },
                    {
                        width: 0,
                        render: (_, template) => (
                            <More
                                size="small"
                                overlay={
                                    <>
                                        <LemonButton fullWidth onClick={() => setEditing(template)}>
                                            Edit
                                        </LemonButton>
                                        <LemonButton
                                            fullWidth
                                            status="danger"
                                            icon={<IconTrash />}
                                            onClick={() => deleteActionTemplate(template.id)}
                                        >
                                            Delete
                                        </LemonButton>
                                    </>
                                }
                            />
                        ),
                    },
                ]}
            />
            {editing && <ActionTemplateEditorModal actionTemplate={editing} onClose={() => setEditing(null)} />}
        </div>
    )
}
