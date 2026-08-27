import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonInputSelect,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { type ConfigVersionApi, type LabelSummaryApi, OutputFieldTypeEnumApi } from '../generated/api.schemas'
import { growthAiEnrichmentRunCreateBodySampleMax } from '../generated/api.zod'
import { aiEnrichmentLogic } from './aiEnrichmentLogic'
import {
    outputFieldsDisabledReason,
    type AIEnrichmentOutputField,
    type AIEnrichmentOutputFieldType,
} from './aiEnrichmentOutputFields'
import { AIEnrichmentResultsTable } from './AIEnrichmentResultsTable'
import { suggestNextVersion } from './aiEnrichmentVersioning'

export const scene: SceneExport = {
    component: AIEnrichmentScene,
    logic: aiEnrichmentLogic,
}

// Derived from the generated enum so a new backend output type shows up in the picker on its own.
const OUTPUT_FIELD_TYPE_OPTIONS: { value: AIEnrichmentOutputFieldType; label: string }[] = Object.values(
    OutputFieldTypeEnumApi
).map((value) => ({ value, label: value.charAt(0).toUpperCase() + value.slice(1) }))

function AIEnrichmentLabelPicker(): JSX.Element {
    const { labels, labelsLoading } = useValues(aiEnrichmentLogic)
    const results = labels?.results ?? []

    const columns: LemonTableColumns<LabelSummaryApi> = [
        {
            title: 'Label',
            key: 'label',
            render: (_, row) => <Link to={urls.aiEnrichment(row.label)}>{row.label}</Link>,
        },
        { title: 'Versions', key: 'version_count', dataIndex: 'version_count' },
        {
            title: 'Active version',
            key: 'active_version',
            render: (_, row) => row.active_version ?? <span className="text-secondary">None</span>,
        },
    ]

    return (
        <div className="space-y-2">
            <h3 className="mb-0">Pick a label</h3>
            <LemonTable
                dataSource={results}
                loading={labelsLoading}
                rowKey={(row) => row.label}
                columns={columns}
                emptyState="No labels have any saved prompt configs yet."
            />
        </div>
    )
}

// Exported for AIEnrichmentScene.test.tsx - covers the Activate discard-confirm gate directly
// against this component rather than the full scene.
export function AIEnrichmentVersionRail(): JSX.Element {
    const {
        selectedLabel,
        versions,
        configsLoading,
        activeVersion,
        selectedVersionId,
        activateResultLoading,
        isEditorDirty,
    } = useValues(aiEnrichmentLogic)
    const { activateVersion, loadVersionIntoEditor } = useActions(aiEnrichmentLogic)

    const selectVersion = (version: ConfigVersionApi): void => {
        if (!isEditorDirty) {
            loadVersionIntoEditor(version)
            return
        }
        LemonDialog.open({
            title: 'Discard unsaved changes?',
            description: `Viewing version ${version.version} will discard your unsaved edits. Nothing is saved until you save as a new version.`,
            primaryButton: {
                children: 'Discard changes',
                status: 'danger',
                onClick: () => loadVersionIntoEditor(version),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const confirmActivate = (version: ConfigVersionApi): void => {
        // Activating reloads and re-selects the newly active version, which discards any unsaved
        // edit the same way selectVersion's dialog does - so the same warning applies here, not
        // just a plain "activate this?" prompt that silently drops the draft.
        LemonDialog.open({
            title: `Activate version ${version.version}?`,
            description: isEditorDirty
                ? 'This discards your unsaved edits and starts computing this version instead of the currently active one. Nothing is saved until you save as a new version.'
                : 'The batch runner will start computing this version instead of the currently active one.',
            primaryButton: {
                children: isEditorDirty ? 'Discard changes and activate' : 'Activate',
                status: isEditorDirty ? 'danger' : undefined,
                onClick: () => activateVersion(version.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const columns: LemonTableColumns<ConfigVersionApi> = [
        {
            title: 'Version',
            key: 'version',
            render: (_, version) => (
                <div className="flex items-center gap-1">
                    <span className={version.id === selectedVersionId ? 'font-semibold' : undefined}>
                        {version.version}
                    </span>
                    {version.is_active && <LemonTag type="success">ACTIVE</LemonTag>}
                </div>
            ),
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, version) => (
                <span className="text-secondary text-xs">
                    {version.created_by_email ?? 'system'} · <TZLabel time={version.created_at} />
                </span>
            ),
        },
        {
            title: '',
            key: 'actions',
            render: (_, version) =>
                version.is_active ? null : (
                    <LemonButton
                        type="secondary"
                        size="small"
                        disabledReason={activateResultLoading ? 'Activation in progress' : undefined}
                        onClick={() => confirmActivate(version)}
                    >
                        Activate
                    </LemonButton>
                ),
        },
    ]

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <h3 className="mb-0">{selectedLabel}</h3>
                <span className="text-secondary text-xs">
                    Live version:{' '}
                    <span className="font-semibold" data-attr="ai-enrichment-active-version">
                        {activeVersion ? activeVersion.version : 'None'}
                    </span>
                </span>
            </div>
            <LemonTable
                dataSource={versions}
                loading={configsLoading}
                rowKey={(version) => version.id}
                columns={columns}
                emptyState="No versions saved yet for this label."
                onRow={(version) => ({
                    // No explicit className: LemonTable's own TableRow already adds
                    // cursor-pointer + a hover background whenever onRow returns an onClick.
                    tabIndex: 0,
                    role: 'button',
                    'aria-label': `View version ${version.version}`,
                    onClick: (e) => {
                        // The Activate button lives in this same row - let its own onClick fire
                        // without also selecting the row underneath it.
                        if ((e.target as HTMLElement).closest('button')) {
                            return
                        }
                        selectVersion(version)
                    },
                    onKeyDown: (e) => {
                        if ((e.target as HTMLElement).closest('button')) {
                            return
                        }
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            selectVersion(version)
                        }
                    },
                })}
            />
        </div>
    )
}

function AIEnrichmentOutputFieldsEditor(): JSX.Element {
    const { editorOutputFields } = useValues(aiEnrichmentLogic)
    const { addOutputField, removeOutputField, updateOutputField, seedDefaultOutputFields } =
        useActions(aiEnrichmentLogic)

    if (editorOutputFields.length === 0) {
        return (
            <div className="flex items-center gap-2">
                <span className="text-secondary text-sm">
                    Output fields are what the model returns. Add at least one to save or test-run.
                </span>
                <LemonButton type="secondary" size="small" onClick={() => seedDefaultOutputFields()}>
                    Start with verdict, confidence, reasoning
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="space-y-1">
            {editorOutputFields.map((field: AIEnrichmentOutputField, index: number) => (
                <div key={index} className="flex items-center gap-2">
                    <LemonInput
                        className="flex-1"
                        placeholder="key, e.g. ai_pilled"
                        value={field.key}
                        onChange={(key) => updateOutputField(index, { key })}
                    />
                    <LemonSelect
                        value={field.type}
                        onChange={(type) => type && updateOutputField(index, { type })}
                        options={OUTPUT_FIELD_TYPE_OPTIONS}
                    />
                    <LemonInput
                        className="flex-[2]"
                        placeholder="Description shown to the model (optional)"
                        value={field.description}
                        onChange={(description) => updateOutputField(index, { description })}
                    />
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        status="danger"
                        onClick={() => removeOutputField(index)}
                        tooltip="Remove field"
                    />
                </div>
            ))}
            <LemonButton icon={<IconPlus />} size="small" type="secondary" onClick={() => addOutputField()}>
                Add field
            </LemonButton>
        </div>
    )
}

function AIEnrichmentEditorPanel(): JSX.Element {
    const { editorPromptText, editorModel, editorInputFields, isEditorDirty, modelOptions, selectedVersion } =
        useValues(aiEnrichmentLogic)
    const { setEditorPromptText, setEditorModel, setEditorInputFields } = useActions(aiEnrichmentLogic)

    return (
        <div className="space-y-2">
            {isEditorDirty && (
                <LemonBanner type="info">
                    Unsaved changes. Versions are frozen once saved, so saving creates a new one.
                </LemonBanner>
            )}
            {selectedVersion && !selectedVersion.is_active && !isEditorDirty && (
                <LemonBanner type="warning">
                    Viewing version {selectedVersion.version}, which is not the active version running in production.
                </LemonBanner>
            )}
            <div className="flex items-center gap-2">
                <span className="font-semibold">Model</span>
                <div className="w-64">
                    <LemonInputSelect
                        mode="single"
                        size="small"
                        value={editorModel ? [editorModel] : []}
                        onChange={(values) => values[0] && setEditorModel(values[0])}
                        options={modelOptions}
                        placeholder="Search models..."
                        data-attr="ai-enrichment-model"
                    />
                </div>
            </div>
            <CodeEditor
                // Remount when a version loads: monaco can mount before async state hydrates and
                // miss the first controlled value update.
                key={selectedVersion?.id ?? 'unloaded'}
                className="border"
                language="markdown"
                value={editorPromptText}
                onChange={(value) => setEditorPromptText(value ?? '')}
                height={320}
                options={{ minimap: { enabled: false }, wordWrap: 'on' }}
            />
            <div className="space-y-1">
                <div className="font-semibold">Input fields</div>
                <div className="text-secondary text-xs">
                    Dotted paths into the org's archived company-data snapshot (e.g. funding.fundingStage), passed to
                    the prompt for each sampled org.
                </div>
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={editorInputFields}
                    onChange={(fields) => setEditorInputFields(fields)}
                    placeholder="Add a payload field and press enter..."
                    data-attr="ai-enrichment-input-fields"
                />
            </div>
            <div className="space-y-1">
                <div className="font-semibold">Output fields</div>
                <div className="text-secondary text-xs">
                    The keys, types, and optional descriptions the model must return for each sampled org.
                </div>
                <AIEnrichmentOutputFieldsEditor />
            </div>
        </div>
    )
}

function inputFieldsDisabledReason(fields: string[]): string | undefined {
    return fields.length > 0 ? undefined : 'Add at least one input field'
}

function runDisabledReason(
    canRun: boolean,
    editorPromptText: string,
    inputReason: string | undefined,
    outputReason: string | undefined
): string | undefined {
    if (canRun) {
        return undefined
    }
    if (!editorPromptText.trim()) {
        return 'Enter a prompt before running'
    }
    if (inputReason) {
        return `${inputReason} before running`
    }
    if (outputReason) {
        return `${outputReason} before running`
    }
    return undefined
}

function AIEnrichmentTestRunControls(): JSX.Element {
    const {
        sampleSize,
        canRun,
        isRunning,
        saveResultLoading,
        editorPromptText,
        editorInputFields,
        editorOutputFields,
    } = useValues(aiEnrichmentLogic)
    const { setSampleSize, runClassification } = useActions(aiEnrichmentLogic)
    const inputReason = inputFieldsDisabledReason(editorInputFields)
    const outputReason = outputFieldsDisabledReason(editorOutputFields)

    return (
        <div className="flex flex-wrap items-end gap-2">
            <div>
                <label className="text-xs font-semibold" htmlFor="ai-enrichment-sample-size">
                    Sample size
                </label>
                <LemonInput
                    id="ai-enrichment-sample-size"
                    type="number"
                    min={1}
                    max={growthAiEnrichmentRunCreateBodySampleMax}
                    value={sampleSize}
                    onChange={(value) => setSampleSize(value ?? 1)}
                />
            </div>
            <LemonButton
                type="primary"
                loading={isRunning}
                disabledReason={
                    saveResultLoading
                        ? 'Save in progress'
                        : runDisabledReason(canRun, editorPromptText, inputReason, outputReason)
                }
                onClick={() => runClassification()}
                data-attr="ai-enrichment-test-run"
            >
                Test run
            </LemonButton>
            <span className="text-secondary text-xs">
                Runs the prompt above (including unsaved edits) against the most recently archived orgs. Nothing is
                saved.
            </span>
        </div>
    )
}

function AIEnrichmentSaveControls(): JSX.Element {
    const { saveResultLoading, selectedLabel, isRunning, editorInputFields, editorOutputFields, versions } =
        useValues(aiEnrichmentLogic)
    const { saveVersion } = useActions(aiEnrichmentLogic)
    const inputReason = inputFieldsDisabledReason(editorInputFields)
    const outputReason = outputFieldsDisabledReason(editorOutputFields)

    return (
        <div className="flex items-center gap-2">
            <LemonButton
                type="secondary"
                loading={saveResultLoading}
                disabledReason={
                    isRunning
                        ? 'Test run in progress'
                        : !selectedLabel
                          ? 'Select a label first'
                          : inputReason
                            ? `${inputReason} before saving`
                            : outputReason
                              ? `${outputReason} before saving`
                              : undefined
                }
                onClick={() =>
                    LemonDialog.openForm({
                        title: 'Save as new version',
                        description:
                            'Versions are immutable once saved. Accept the suggested version, or pick your own.',
                        initialValues: { version: suggestNextVersion(versions) },
                        content: (
                            <LemonField name="version" label="Version">
                                <LemonInput autoFocus />
                            </LemonField>
                        ),
                        errors: { version: (value) => (!value?.trim() ? 'Enter a version name' : undefined) },
                        onSubmit: ({ version }) => saveVersion(version),
                    })
                }
                data-attr="ai-enrichment-save"
            >
                Save as new version
            </LemonButton>
            <span className="text-secondary text-xs">
                Freezes the current prompt, model, inputs, and outputs into a new, immutable version.
            </span>
        </div>
    )
}

function AIEnrichmentEditor(): JSX.Element {
    return (
        <div className="flex gap-4">
            <div className="min-w-0 flex-1 space-y-4">
                <AIEnrichmentVersionRail />
                <AIEnrichmentEditorPanel />
                <AIEnrichmentTestRunControls />
                <AIEnrichmentSaveControls />
                <AIEnrichmentResultsTable />
            </div>
        </div>
    )
}

export function AIEnrichmentScene(): JSX.Element {
    const { user } = useValues(userLogic)
    const { selectedLabel } = useValues(aiEnrichmentLogic)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="This page is only accessible to staff users." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="AI enrichment"
                description="See which classifier version is live for a label, edit and test-run a draft, then save it as a new version and switch which one is live."
                resourceType={{ type: 'llm_analytics' }}
            />
            {selectedLabel ? <AIEnrichmentEditor /> : <AIEnrichmentLabelPicker />}
        </SceneContent>
    )
}
