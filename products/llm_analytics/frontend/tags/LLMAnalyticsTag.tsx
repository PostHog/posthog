import { BindLogic, useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { IconArrowLeft, IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import { getModelPickerFooterLink, ModelPicker } from '../ModelPicker'
import { modelPickerLogic } from '../modelPickerLogic'
import { HOG_TAGGER_EXAMPLES } from './hogTaggerExamples'
import { HogTestResult, TagRun, llmTaggerLogic } from './llmTaggerLogic'

const DEFAULT_HOG_SOURCE = `// Return a list of tag names that apply to this generation
// Available globals: input, output, properties, event, tags
let result := []
if (output ilike '%billing%') {
    result := arrayPushBack(result, 'billing')
    print('Found: billing')
}
return result`
import { TaggerConditionSet } from './types'

export const scene: SceneExport = {
    component: LLMAnalyticsTagScene,
    logic: llmTaggerLogic,
    paramsToProps: ({ params }): { id: string } => ({ id: params.id || 'new' }),
    productKey: ProductKey.LLM_ANALYTICS,
}

function TagDefinitionsEditor({ id }: { id: string }): JSX.Element {
    const { taggerForm } = useValues(llmTaggerLogic({ id }))
    const { addTag, removeTag, updateTag } = useActions(llmTaggerLogic({ id }))

    return (
        <div className="space-y-2">
            <div className="flex justify-between items-center">
                <label className="font-semibold">Tags</label>
                <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={addTag}>
                    Add tag
                </LemonButton>
            </div>
            <p className="text-muted text-sm">
                Define the tags the LLM can assign. Add descriptions to help it tag more accurately.
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

function TaggerModelPicker({ id }: { id: string }): JSX.Element {
    const {
        hasByokKeys,
        byokModels,
        trialModels,
        providerModelGroups,
        trialProviderModelGroups,
        byokModelsLoading,
        trialModelsLoading,
        providerKeysLoading,
    } = useValues(modelPickerLogic)
    const { selectedModel, selectedPickerProviderKeyId } = useValues(llmTaggerLogic({ id }))
    const { selectModelFromPicker } = useActions(llmTaggerLogic({ id }))

    const allModels = hasByokKeys ? byokModels : trialModels
    const selectedModelName = allModels.find((m) => m.id === selectedModel)?.name
    const groups = hasByokKeys ? providerModelGroups : trialProviderModelGroups
    const loading = hasByokKeys ? byokModelsLoading || providerKeysLoading : trialModelsLoading

    const footerLink = getModelPickerFooterLink(hasByokKeys)

    return (
        <div className="bg-bg-light border rounded p-6">
            <h3 className="text-lg font-semibold mb-2">Model</h3>
            <p className="text-muted text-sm mb-4">
                Select which LLM provider and model to use for running this tagger.
            </p>

            <div className="space-y-4">
                <Field name="model" label="Model">
                    <ModelPicker
                        model={selectedModel}
                        selectedProviderKeyId={selectedPickerProviderKeyId}
                        onSelect={selectModelFromPicker}
                        groups={groups}
                        loading={loading}
                        footerLink={footerLink}
                        selectedModelName={selectedModelName}
                        data-attr="tagger-model-selector"
                    />
                </Field>
            </div>
        </div>
    )
}

function TaggerTriggers({ id }: { id: string }): JSX.Element {
    const { taggerForm } = useValues(llmTaggerLogic({ id }))
    const { setConditions } = useActions(llmTaggerLogic({ id }))

    const conditions = taggerForm.conditions

    const addConditionSet = (): void => {
        const newCondition: TaggerConditionSet = {
            id: `cond-${Date.now()}`,
            rollout_percentage: 100,
            properties: [],
        }
        setConditions([...conditions, newCondition])
    }

    const updateConditionSet = (index: number, updates: Partial<TaggerConditionSet>): void => {
        const updated = conditions.map((condition, i) => (i === index ? { ...condition, ...updates } : condition))
        setConditions(updated)
    }

    const removeConditionSet = (index: number): void => {
        if (conditions.length === 1) {
            return
        }
        setConditions(conditions.filter((_, i) => i !== index))
    }

    const duplicateConditionSet = (index: number): void => {
        const duplicated: TaggerConditionSet = {
            ...conditions[index],
            id: `cond-${Date.now()}`,
        }
        const updated = [...conditions]
        updated.splice(index + 1, 0, duplicated)
        setConditions(updated)
    }

    return (
        <div className="space-y-6">
            <div className="text-sm text-muted">
                Each condition set defines when this tagger should trigger. If multiple condition sets exist, the tagger
                will trigger if ANY of them match (OR logic).
            </div>

            {conditions.map((condition, index) => {
                const percentageValue = condition.rollout_percentage || 0

                return (
                    <div key={condition.id} className="bg-bg-light border rounded p-4 space-y-4">
                        <div className="flex justify-between items-center">
                            <div className="flex items-center gap-2">
                                <h4 className="font-semibold">Condition set {index + 1}</h4>
                                {conditions.length > 1 && (
                                    <div className="text-sm text-muted">{index === 0 ? 'IF' : 'OR IF'}</div>
                                )}
                            </div>
                            <div className="flex gap-1">
                                <LemonButton
                                    icon={<IconCopy />}
                                    size="small"
                                    type="secondary"
                                    onClick={() => duplicateConditionSet(index)}
                                    tooltip="Duplicate condition set"
                                />
                                {conditions.length > 1 && (
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        type="secondary"
                                        status="danger"
                                        onClick={() => removeConditionSet(index)}
                                        tooltip="Remove condition set"
                                    />
                                )}
                            </div>
                        </div>

                        <div className="space-y-2">
                            <label className="block text-sm font-medium">
                                Sampling percentage <span className="text-danger">*</span>
                            </label>
                            <div className="flex items-center gap-4 max-w-md">
                                <div className="flex-1">
                                    <LemonSlider
                                        value={percentageValue}
                                        onChange={(value) => updateConditionSet(index, { rollout_percentage: value })}
                                        min={0.1}
                                        max={100}
                                        step={0.1}
                                    />
                                </div>
                                <div className="w-24">
                                    <LemonInput
                                        type="number"
                                        value={percentageValue}
                                        onChange={(value) =>
                                            updateConditionSet(index, { rollout_percentage: Number(value) || 0 })
                                        }
                                        min={0.1}
                                        max={100}
                                        step={0.1}
                                        suffix={<span>%</span>}
                                        placeholder="Set percentage"
                                        status={percentageValue === 0 ? 'danger' : undefined}
                                    />
                                </div>
                            </div>
                            {percentageValue === 0 ? (
                                <div className="text-xs text-danger">
                                    Please set a sampling percentage between 0.1% and 100%
                                </div>
                            ) : (
                                <div className="text-xs text-muted">
                                    This tagger will run on {percentageValue.toFixed(2)}% of matching generations
                                </div>
                            )}
                        </div>

                        <div className="space-y-2">
                            <label className="block text-sm font-medium">Filter conditions</label>
                            <div className="text-sm text-muted mb-2">
                                Filter by generation event properties or person properties to target specific
                                generations. Leave empty to match all generations.
                            </div>
                            <PropertyFilters
                                propertyFilters={condition.properties}
                                onChange={(properties) => updateConditionSet(index, { properties })}
                                pageKey={`tagger-condition-${condition.id}`}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.EventMetadata,
                                    TaxonomicFilterGroupType.PersonProperties,
                                ]}
                                addText="Add filter condition"
                                hasRowOperator={false}
                                sendAllKeyUpdates
                                allowRelativeDateOptions={false}
                            />
                        </div>
                    </div>
                )
            })}

            <div className="flex justify-center">
                <LemonButton type="secondary" icon={<IconPlus />} onClick={addConditionSet}>
                    Add condition set
                </LemonButton>
            </div>
        </div>
    )
}

function HogTaggerTestSection({ id }: { id: string }): JSX.Element {
    const { hogTestResults, hogTestLoading } = useValues(llmTaggerLogic({ id }))
    const { testHogTagger, clearHogTestResults } = useActions(llmTaggerLogic({ id }))

    return (
        <div className="mt-4 space-y-3">
            <div className="flex gap-2">
                <LemonButton type="secondary" size="small" onClick={testHogTagger} loading={hogTestLoading}>
                    Test on recent generations
                </LemonButton>
                {hogTestResults && (
                    <LemonButton type="tertiary" size="small" onClick={clearHogTestResults}>
                        Clear
                    </LemonButton>
                )}
            </div>

            {hogTestResults && (
                <LemonTable
                    columns={[
                        {
                            title: 'Input',
                            key: 'input',
                            render: (_, row: HogTestResult) => (
                                <div className="max-w-xs text-sm truncate">{row.input_preview}</div>
                            ),
                        },
                        {
                            title: 'Output',
                            key: 'output',
                            render: (_, row: HogTestResult) => (
                                <div className="max-w-xs text-sm truncate">{row.output_preview}</div>
                            ),
                        },
                        {
                            title: 'Tags',
                            key: 'tags',
                            render: (_, row: HogTestResult) =>
                                row.error ? (
                                    <LemonTag type="danger">{row.error}</LemonTag>
                                ) : (
                                    <div className="flex flex-wrap gap-1">
                                        {row.tags.length > 0 ? (
                                            row.tags.map((tag: string) => (
                                                <LemonTag key={tag} type="highlight">
                                                    {tag}
                                                </LemonTag>
                                            ))
                                        ) : (
                                            <span className="text-muted text-sm">No tags</span>
                                        )}
                                    </div>
                                ),
                        },
                        {
                            title: 'Reasoning',
                            key: 'reasoning',
                            render: (_, row: HogTestResult) =>
                                row.reasoning ? (
                                    <Tooltip title={row.reasoning} placement="top">
                                        <div className="max-w-xs text-sm truncate cursor-default">{row.reasoning}</div>
                                    </Tooltip>
                                ) : (
                                    <span className="text-muted text-sm">-</span>
                                ),
                        },
                    ]}
                    dataSource={hogTestResults}
                    rowKey="event_uuid"
                    size="small"
                    emptyState={<span className="text-muted text-sm">No recent generations found</span>}
                />
            )}
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
                        <h3 className="text-lg font-semibold">Tag config</h3>

                        <div>
                            <label className="font-semibold">Method</label>
                            <LemonSelect
                                value={taggerForm.tagger_type}
                                onChange={(value) => {
                                    setTaggerFormValues({ tagger_type: value })
                                    // Reset config when switching types
                                    if (value === 'hog') {
                                        setTaggerFormValues({
                                            tagger_type: value,
                                            tagger_config: {
                                                source: DEFAULT_HOG_SOURCE,
                                                tags: taggerForm.tagger_config.tags,
                                            },
                                        })
                                    } else {
                                        setTaggerFormValues({
                                            tagger_type: value,
                                            tagger_config: {
                                                prompt: '',
                                                tags: taggerForm.tagger_config.tags,
                                                min_tags: 0,
                                                max_tags: null,
                                            },
                                        })
                                    }
                                }}
                                options={[
                                    { value: 'llm', label: 'LLM' },
                                    { value: 'hog', label: 'Hog code' },
                                ]}
                                fullWidth
                            />
                            <p className="text-muted text-sm mt-1">
                                {taggerForm.tagger_type === 'hog'
                                    ? 'Run deterministic Hog code against each generation. No LLM cost, instant results.'
                                    : 'Use an LLM to intelligently tag each generation based on a prompt.'}
                            </p>
                        </div>

                        {taggerForm.tagger_type === 'hog' ? (
                            <div>
                                <label className="font-semibold">Hog code</label>
                                <p className="text-muted text-sm mb-2">
                                    Return a list of tag names. Available globals: input, output, properties, event,
                                    tags.
                                </p>
                                <div className="flex flex-wrap gap-1.5 mb-3">
                                    {HOG_TAGGER_EXAMPLES.map((example) => (
                                        <LemonButton
                                            key={example.label}
                                            type="secondary"
                                            size="xsmall"
                                            onClick={() =>
                                                setTaggerFormValues({
                                                    tagger_config: {
                                                        ...taggerForm.tagger_config,
                                                        source: example.source,
                                                    },
                                                })
                                            }
                                        >
                                            {example.label}
                                        </LemonButton>
                                    ))}
                                </div>
                                <CodeEditorResizeable
                                    language="hog"
                                    value={'source' in taggerForm.tagger_config ? taggerForm.tagger_config.source : ''}
                                    onChange={(value) =>
                                        setTaggerFormValues({
                                            tagger_config: { ...taggerForm.tagger_config, source: value ?? '' },
                                        })
                                    }
                                    height={200}
                                />
                                <HogTaggerTestSection id={id} />
                            </div>
                        ) : (
                            <div>
                                <label className="font-semibold">Prompt</label>
                                <p className="text-muted text-sm mb-1">
                                    Instructions for the LLM on how to tag generations.
                                </p>
                                <LemonTextArea
                                    placeholder="e.g. Which product features were discussed or used in this generation?"
                                    value={'prompt' in taggerForm.tagger_config ? taggerForm.tagger_config.prompt : ''}
                                    onChange={(value) =>
                                        setTaggerFormValues({
                                            tagger_config: { ...taggerForm.tagger_config, prompt: value },
                                        })
                                    }
                                    minRows={3}
                                />
                            </div>
                        )}

                        {taggerForm.tagger_type !== 'hog' && <TagDefinitionsEditor id={id} />}

                        {taggerForm.tagger_type !== 'hog' && (
                            <div className="flex gap-4">
                                <div>
                                    <label className="font-semibold">Min tags</label>
                                    <LemonInput
                                        type="number"
                                        min={0}
                                        value={
                                            'min_tags' in taggerForm.tagger_config
                                                ? taggerForm.tagger_config.min_tags
                                                : 0
                                        }
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
                                        value={
                                            'max_tags' in taggerForm.tagger_config
                                                ? (taggerForm.tagger_config.max_tags ?? undefined)
                                                : undefined
                                        }
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
                        )}
                    </div>

                    {/* Model Configuration (LLM only) */}
                    {taggerForm.tagger_type !== 'hog' && <TaggerModelPicker id={id} />}

                    {/* Trigger Configuration */}
                    <div className="border-t pt-4 space-y-4">
                        <h3 className="text-lg font-semibold">Triggers</h3>
                        <TaggerTriggers id={id} />
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
                        <LemonButton type="secondary" to={urls.llmAnalyticsTags()}>
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

function TagRunsChart({ id }: { id: string }): JSX.Element | null {
    const { runsChartQuery } = useValues(llmTaggerLogic({ id }))

    if (!runsChartQuery) {
        return null
    }

    return (
        <div className="bg-bg-light rounded p-4 mb-4 h-72 flex flex-col InsightCard">
            <h3 className="text-base font-semibold mb-1">Tag distribution over time</h3>
            <div className="flex-1 flex flex-col min-h-0">
                <Query
                    query={{ kind: NodeKind.InsightVizNode, source: runsChartQuery } as InsightVizNode}
                    readOnly
                    embedded
                    inSharedMode
                    context={{
                        insightProps: {
                            dashboardItemId: `new-tagger-runs-chart-${id}`,
                            dataNodeCollectionId: `tagger-runs-${id}`,
                        },
                    }}
                />
            </div>
        </div>
    )
}

function TagRunsTable({ id }: { id: string }): JSX.Element {
    const { tagRuns, tagRunsLoading, dateFilter } = useValues(llmTaggerLogic({ id }))
    const { loadTagRuns, setDates } = useActions(llmTaggerLogic({ id }))

    const columns: LemonTableColumns<TagRun> = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
            sorter: (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        },
        {
            title: 'Generation',
            key: 'generation',
            render: (_, run) =>
                run.trace_id && run.target_event_id ? (
                    <div className="font-mono text-sm">
                        <Link
                            to={urls.llmAnalyticsTrace(run.trace_id, { event: run.target_event_id })}
                            className="text-primary"
                        >
                            {run.target_event_id.slice(0, 12)}...
                        </Link>
                    </div>
                ) : (
                    <span className="text-muted text-sm">-</span>
                ),
        },
        {
            title: 'Tags',
            key: 'tags',
            render: (_, run) => (
                <div className="flex flex-wrap gap-1">
                    {run.tags.length > 0 ? (
                        run.tags.map((tag: string) => (
                            <LemonTag key={tag} type="highlight">
                                {tag}
                            </LemonTag>
                        ))
                    ) : (
                        <span className="text-muted text-sm">No tags</span>
                    )}
                </div>
            ),
        },
        {
            title: 'Reasoning',
            key: 'reasoning',
            render: (_, run) =>
                run.reasoning ? (
                    <Tooltip title={run.reasoning} placement="top">
                        <div className="max-w-md text-sm truncate cursor-default">{run.reasoning}</div>
                    </Tooltip>
                ) : (
                    <span className="text-muted text-sm">-</span>
                ),
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <div className="flex items-center gap-3">
                    <p className="text-muted text-sm m-0">Tag runs for this tagger.</p>
                    <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                </div>
                <LemonButton type="secondary" size="small" onClick={loadTagRuns}>
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={tagRuns}
                loading={tagRunsLoading}
                rowKey="target_event_id"
                pagination={{ pageSize: 20 }}
                nouns={['run', 'runs']}
                emptyState={
                    <div className="text-center py-8 text-muted">
                        No tag runs yet. Enable this tagger and send some generations to see results.
                    </div>
                }
            />
        </div>
    )
}

export function LLMAnalyticsTagScene({ id }: { id?: string }): JSX.Element {
    const taggerId = id || 'new'
    const isNew = taggerId === 'new'
    const { tagger, taggerLoading, activeTab } = useValues(llmTaggerLogic({ id: taggerId }))
    const { setActiveTab } = useActions(llmTaggerLogic({ id: taggerId }))

    if (taggerLoading) {
        return (
            <SceneContent>
                <LemonSkeleton className="w-full h-96" />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <div className="space-y-6">
                {/* Header */}
                <div className="flex justify-between items-start pb-4 border-b">
                    <div className="space-y-2">
                        <h1 className="text-2xl font-semibold">{isNew ? 'New tagger' : tagger?.name || 'Tagger'}</h1>
                        {!isNew && tagger && (
                            <div className="flex items-center gap-2">
                                <LemonTag type={tagger.enabled ? 'success' : 'default'}>
                                    {tagger.enabled ? 'Enabled' : 'Disabled'}
                                </LemonTag>
                            </div>
                        )}
                    </div>
                    <LemonButton type="secondary" icon={<IconArrowLeft />} to={urls.llmAnalyticsTags()}>
                        Back
                    </LemonButton>
                </div>

                <LemonTabs
                    activeKey={isNew ? 'configuration' : activeTab}
                    onChange={(key) => setActiveTab(key as 'runs' | 'configuration')}
                    data-attr="llma-tagger-tabs"
                    tabs={[
                        ...(!isNew
                            ? [
                                  {
                                      key: 'runs',
                                      label: 'Runs',
                                      content: (
                                          <div className="max-w-6xl">
                                              <TagRunsChart id={taggerId} />
                                              <TagRunsTable id={taggerId} />
                                          </div>
                                      ),
                                  },
                              ]
                            : []),
                        {
                            key: 'configuration',
                            label: 'Configuration',
                            content: <LLMAnalyticsTaggerForm id={taggerId} />,
                        },
                    ]}
                />
            </div>
        </SceneContent>
    )
}
