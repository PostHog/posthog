import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { llmTaggerLogic } from './llmTaggerLogic'

export const scene: SceneExport = {
    component: LLMAnalyticsTaggerScene,
    logic: llmTaggerLogic,
    paramsToProps: ({ params }): { id: string } => ({ id: params.id || 'new' }),
    productKey: ProductKey.LLM_ANALYTICS,
}

function TagDefinitionsEditor(): JSX.Element {
    const { taggerForm } = useValues(llmTaggerLogic({ id: '' }))
    const { addTag, removeTag, updateTag } = useActions(llmTaggerLogic({ id: '' }))

    return (
        <div className="space-y-2">
            <div className="flex justify-between items-center">
                <label className="font-semibold">Tags</label>
                <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={addTag}>
                    Add tag
                </LemonButton>
            </div>
            <p className="text-muted text-sm">
                Define the tags the LLM can assign. Add descriptions to help it classify more accurately.
            </p>
            {taggerForm.tagger_config.tags.map((tag, index) => (
                <div key={index} className="flex gap-2 items-start">
                    <div className="flex-1">
                        <LemonInput
                            placeholder="Tag name"
                            value={tag.name}
                            onChange={(value) => updateTag(index, 'name', value)}
                            size="small"
                        />
                    </div>
                    <div className="flex-2">
                        <LemonInput
                            placeholder="Description (optional)"
                            value={tag.description || ''}
                            onChange={(value) => updateTag(index, 'description', value)}
                            size="small"
                        />
                    </div>
                    <LemonButton
                        type="secondary"
                        status="danger"
                        size="small"
                        icon={<IconTrash />}
                        onClick={() => removeTag(index)}
                        disabledReason={
                            taggerForm.tagger_config.tags.length <= 1 ? 'At least one tag is required' : undefined
                        }
                    />
                </div>
            ))}
        </div>
    )
}

function LLMAnalyticsTaggerForm({ id }: { id: string }): JSX.Element {
    const logic = llmTaggerLogic({ id })
    const { taggerForm, taggerFormChanged, isTaggerFormSubmitting } = useValues(logic)
    const { setTaggerFormValues, submitTaggerForm, deleteTagger } = useActions(logic)

    return (
        <BindLogic logic={llmTaggerLogic} props={{ id }}>
            <Form logic={llmTaggerLogic} props={{ id }} formKey="taggerForm">
                <div className="space-y-6 max-w-3xl">
                    <div className="space-y-4">
                        <div>
                            <label className="font-semibold">Name</label>
                            <LemonInput
                                placeholder="e.g. Product feature tagger"
                                value={taggerForm.name}
                                onChange={(value) => setTaggerFormValues({ name: value })}
                            />
                        </div>

                        <div>
                            <label className="font-semibold">Description</label>
                            <LemonInput
                                placeholder="Optional description"
                                value={taggerForm.description}
                                onChange={(value) => setTaggerFormValues({ description: value })}
                            />
                        </div>

                        <div className="flex items-center gap-2">
                            <LemonSwitch
                                checked={taggerForm.enabled}
                                onChange={(checked) => setTaggerFormValues({ enabled: checked })}
                                label="Enabled"
                            />
                        </div>
                    </div>

                    <div className="border-t pt-4 space-y-4">
                        <h3 className="text-lg font-semibold">Classification config</h3>

                        <div>
                            <label className="font-semibold">Prompt</label>
                            <p className="text-muted text-sm mb-1">
                                Instructions for the LLM on how to classify generations.
                            </p>
                            <LemonTextArea
                                placeholder="e.g. Which product features were discussed or used in this generation?"
                                value={taggerForm.tagger_config.prompt}
                                onChange={(value) =>
                                    setTaggerFormValues({
                                        tagger_config: { ...taggerForm.tagger_config, prompt: value },
                                    })
                                }
                                minRows={3}
                            />
                        </div>

                        <TagDefinitionsEditor />

                        <div className="flex gap-4">
                            <div>
                                <label className="font-semibold">Min tags</label>
                                <LemonInput
                                    type="number"
                                    min={0}
                                    value={taggerForm.tagger_config.min_tags}
                                    onChange={(value) =>
                                        setTaggerFormValues({
                                            tagger_config: {
                                                ...taggerForm.tagger_config,
                                                min_tags: value ?? 0,
                                            },
                                        })
                                    }
                                    size="small"
                                    className="w-24"
                                />
                            </div>
                            <div>
                                <label className="font-semibold">Max tags</label>
                                <LemonInput
                                    type="number"
                                    min={1}
                                    value={taggerForm.tagger_config.max_tags ?? undefined}
                                    onChange={(value) =>
                                        setTaggerFormValues({
                                            tagger_config: {
                                                ...taggerForm.tagger_config,
                                                max_tags: value ?? null,
                                            },
                                        })
                                    }
                                    size="small"
                                    className="w-24"
                                    placeholder="No limit"
                                />
                            </div>
                        </div>
                    </div>

                    <div className="flex gap-2 pt-4 border-t">
                        <LemonButton
                            type="primary"
                            onClick={submitTaggerForm}
                            loading={isTaggerFormSubmitting}
                            disabledReason={!taggerFormChanged && id !== 'new' ? 'No changes to save' : undefined}
                        >
                            {id === 'new' ? 'Create tagger' : 'Save changes'}
                        </LemonButton>
                        <LemonButton type="secondary" to={urls.llmAnalyticsTaggers()}>
                            Cancel
                        </LemonButton>
                        {id !== 'new' && (
                            <LemonButton type="secondary" status="danger" className="ml-auto" onClick={deleteTagger}>
                                Delete
                            </LemonButton>
                        )}
                    </div>
                </div>
            </Form>
        </BindLogic>
    )
}

export function LLMAnalyticsTaggerScene({ id }: { id?: string }): JSX.Element {
    const taggerId = id || 'new'
    const isNew = taggerId === 'new'

    return (
        <SceneContent>
            <SceneTitleSection
                name={isNew ? 'New tagger' : 'Edit tagger'}
                description={isNew ? 'Create a new AI-powered tagger.' : 'Edit tagger configuration.'}
                resourceType={{
                    type: 'llm_taggers',
                }}
            />
            <LLMAnalyticsTaggerForm id={taggerId} />
        </SceneContent>
    )
}
