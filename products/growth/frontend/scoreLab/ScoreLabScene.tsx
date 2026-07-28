import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonInput,
    LemonSelect,
    LemonSwitch,
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
import { growthScoreLabRunCreateBodySampleMax } from '../generated/api.zod'
import { ScoreLabInputFieldsPicker } from './ScoreLabInputFieldsPicker'
import { inputDisabledReason } from './scoreLabInputPayload'
import { scoreLabLogic } from './scoreLabLogic'
import {
    outputFieldsDisabledReason,
    type ScoreLabOutputField,
    type ScoreLabOutputFieldType,
} from './scoreLabOutputFields'
import { SCORE_LAB_QUERY_EXAMPLES, SCORE_LAB_REFERENCE_TABLES } from './scoreLabQueryExamples'
import { ScoreLabResultsTable } from './ScoreLabResultsTable'

export const scene: SceneExport = {
    component: ScoreLabScene,
    logic: scoreLabLogic,
}

// Derived from the generated enum so a new backend output type shows up in the picker on its own.
const OUTPUT_FIELD_TYPE_OPTIONS: { value: ScoreLabOutputFieldType; label: string }[] = Object.values(
    OutputFieldTypeEnumApi
).map((value) => ({ value, label: value.charAt(0).toUpperCase() + value.slice(1) }))

function ScoreLabLabelPicker(): JSX.Element {
    const { labels, labelsLoading } = useValues(scoreLabLogic)
    const results = labels?.results ?? []

    const columns: LemonTableColumns<LabelSummaryApi> = [
        {
            title: 'Label',
            key: 'label',
            render: (_, row) => <Link to={urls.scoreLab(row.label)}>{row.label}</Link>,
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

function ScoreLabVersionPicker(): JSX.Element {
    const {
        selectedLabel,
        versions,
        configsLoading,
        selectedVersionId,
        selectedVersion,
        activateResultLoading,
        renameResultLoading,
        isEditorDirty,
    } = useValues(scoreLabLogic)
    const { loadVersionIntoEditor, activateVersion, renameConfig } = useActions(scoreLabLogic)

    const selectVersion = (version: ConfigVersionApi): void => {
        if (!isEditorDirty) {
            loadVersionIntoEditor(version)
            return
        }
        LemonDialog.open({
            title: 'Discard unsaved changes?',
            description: `Loading version ${version.version} will discard your unsaved edits.`,
            primaryButton: {
                children: 'Discard changes',
                status: 'danger',
                onClick: () => loadVersionIntoEditor(version),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonButton
                size="small"
                tooltip={`Rename the ${selectedLabel} label`}
                loading={renameResultLoading}
                onClick={() =>
                    selectedVersion &&
                    LemonDialog.openForm({
                        title: `Rename ${selectedLabel}`,
                        description: `A label is shared by all of its versions, so this renames every one of the ${versions.length}. It does not change what any of them do.`,
                        initialValues: { label: selectedLabel },
                        content: (
                            <LemonField name="label" label="Label name">
                                <LemonInput autoFocus />
                            </LemonField>
                        ),
                        errors: { label: (value) => (!value?.trim() ? 'Enter a label name' : undefined) },
                        onSubmit: ({ label }) =>
                            label !== selectedLabel ? renameConfig({ configId: selectedVersion.id, label }) : undefined,
                    })
                }
            >
                <h3 className="mb-0">{selectedLabel}</h3>
            </LemonButton>
            <span className="text-secondary">/</span>
            <LemonSelect
                value={selectedVersionId}
                loading={configsLoading}
                placeholder="No versions saved yet"
                onChange={(id) => {
                    const version = versions.find((candidate) => candidate.id === id)
                    if (version) {
                        selectVersion(version)
                    }
                }}
                options={versions.map((version) => ({
                    value: version.id,
                    label: version.version,
                    labelInMenu: (
                        <div>
                            <div className="flex items-center gap-1">
                                <span className="font-semibold">{version.version}</span>
                                {version.is_active && <LemonTag type="success">ACTIVE</LemonTag>}
                            </div>
                            <div className="text-secondary text-xs">
                                {version.created_by_email ?? 'system'} · <TZLabel time={version.created_at} />
                            </div>
                        </div>
                    ),
                }))}
            />
            {selectedVersion?.is_active ? (
                <LemonTag type="success">ACTIVE</LemonTag>
            ) : (
                selectedVersion && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={activateResultLoading}
                        onClick={() =>
                            LemonDialog.open({
                                title: `Activate version ${selectedVersion.version}?`,
                                description:
                                    'The batch runner will start computing this version instead of the currently active one.',
                                primaryButton: {
                                    children: 'Activate',
                                    onClick: () => activateVersion(selectedVersion.id),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                    >
                        Activate
                    </LemonButton>
                )
            )}
        </div>
    )
}

function ScoreLabOutputFieldsEditor(): JSX.Element {
    const { editorOutputFields } = useValues(scoreLabLogic)
    const { addOutputField, removeOutputField, updateOutputField, seedDefaultOutputFields } = useActions(scoreLabLogic)

    if (editorOutputFields.length === 0) {
        return (
            <div className="flex items-center gap-2">
                <span className="text-secondary text-sm">
                    Output fields are what the model returns. Add at least one to run.
                </span>
                <LemonButton type="secondary" size="small" onClick={() => seedDefaultOutputFields()}>
                    Start with verdict, confidence, reasoning
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="space-y-1">
            {editorOutputFields.map((field: ScoreLabOutputField, index: number) => (
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

function ScoreLabQueryEditor({
    active,
    onActiveChange,
    value,
    onChange,
}: {
    active: boolean
    onActiveChange: (active: boolean) => void
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <LemonSwitch checked={active} onChange={onActiveChange} label="Use this query as the input" bordered />
            <CodeEditor
                className="border"
                language="hogQL"
                value={value}
                onChange={(v) => onChange(v ?? '')}
                height={160}
                options={{ minimap: { enabled: false }, wordWrap: 'on', readOnly: !active }}
            />
            <div className="flex flex-wrap gap-1.5">
                {SCORE_LAB_QUERY_EXAMPLES.map((example) => (
                    <LemonButton
                        key={example.label}
                        type="secondary"
                        size="xsmall"
                        onClick={() => onChange(example.query)}
                    >
                        {example.label}
                    </LemonButton>
                ))}
            </div>
            <div className="bg-bg-light border rounded p-3 space-y-2 text-xs text-secondary">
                <p className="m-0">
                    Runs as a HogQL <code>SELECT</code> against this project. Select from <code>events</code>,{' '}
                    <code>persons</code>, <code>groups</code>, or a synced data warehouse table. Each result row becomes
                    one classification input, and every column in that row is passed to the prompt.
                </p>
                {SCORE_LAB_REFERENCE_TABLES.map((table) => (
                    <div key={table.table}>
                        <div className="font-semibold text-default">
                            <code>{table.table}</code>: {table.description}
                        </div>
                        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                            {table.columns.map((column) => (
                                <span key={column.name}>
                                    <code>{column.name}</code> <span>{column.type}</span>
                                </span>
                            ))}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

function ScoreLabEditorPanel(): JSX.Element {
    const {
        editorPromptText,
        editorModel,
        editorInputFields,
        editorInputMode,
        editorInputQuery,
        isEditorDirty,
        modelOptions,
        selectedVersion,
        selectedVersionId,
    } = useValues(scoreLabLogic)
    const { setEditorPromptText, setEditorModel, setEditorInputFields, setEditorInputMode, setEditorInputQuery } =
        useActions(scoreLabLogic)

    return (
        <div className="space-y-2">
            {isEditorDirty && (
                <LemonBanner type="info">
                    Unsaved changes. Versions are frozen once saved, so this becomes a new one.
                </LemonBanner>
            )}
            {selectedVersion && !selectedVersion.is_active && (
                <LemonBanner type="warning">
                    Viewing version {selectedVersion.version}, which is not the active version running in production.
                </LemonBanner>
            )}
            <div className="flex items-center gap-2">
                <span className="font-semibold">Model</span>
                <LemonSelect
                    value={editorModel}
                    onChange={(value) => value && setEditorModel(value)}
                    options={modelOptions}
                />
            </div>
            <CodeEditor
                // Remount when a version loads: monaco can mount before async state hydrates
                // and miss the first controlled value update.
                key={selectedVersionId ?? 'unloaded'}
                className="border"
                language="markdown"
                value={editorPromptText}
                onChange={(value) => setEditorPromptText(value ?? '')}
                height={320}
                options={{ minimap: { enabled: false }, wordWrap: 'on' }}
            />
            <div className="space-y-1">
                <span className="font-semibold">Input</span>
                <div className="space-y-1">
                    <span className="text-secondary text-xs">
                        {editorInputMode === 'fields'
                            ? "Fields from the org's archived company-data snapshot, passed to the prompt for each sampled org."
                            : 'Not used while the query below is active.'}
                    </span>
                    <ScoreLabInputFieldsPicker
                        value={editorInputFields}
                        onChange={setEditorInputFields}
                        disabled={editorInputMode === 'query'}
                    />
                </div>
                {/* Expanding this only reveals the query editor; it never changes editorInputMode by
                    itself, so reading the reference doesn't silently swap what gets sent on save/run.
                    Keyed by version so loading a query-mode config opens it without coupling later
                    manual expand/collapse to the mode. */}
                <LemonCollapse
                    key={selectedVersionId ?? 'unloaded'}
                    defaultActiveKey={editorInputMode === 'query' ? 'query' : undefined}
                    panels={[
                        {
                            key: 'query',
                            // The switch lives inside the panel, so a collapsed header is the only
                            // thing on screen when query mode is on. It has to say so itself.
                            header: (
                                <span className="flex min-w-0 items-center gap-2">
                                    <span className="truncate">Advanced: write a HogQL query</span>
                                    {editorInputMode === 'query' && (
                                        <LemonTag type="primary" size="small" className="shrink-0">
                                            Active
                                        </LemonTag>
                                    )}
                                </span>
                            ),
                            content: (
                                <ScoreLabQueryEditor
                                    active={editorInputMode === 'query'}
                                    onActiveChange={(active) => setEditorInputMode(active ? 'query' : 'fields')}
                                    value={editorInputQuery}
                                    onChange={setEditorInputQuery}
                                />
                            ),
                        },
                    ]}
                />
            </div>
            <div className="space-y-1">
                <span className="font-semibold">Output fields</span>
                <ScoreLabOutputFieldsEditor />
            </div>
        </div>
    )
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

function ScoreLabRunControls(): JSX.Element {
    const {
        sampleSize,
        containsFilter,
        canRun,
        isRunning,
        saveResultLoading,
        editorPromptText,
        editorInputMode,
        editorInputFields,
        editorInputQuery,
        editorOutputFields,
    } = useValues(scoreLabLogic)
    const { setSampleSize, setContainsFilter, runClassification } = useActions(scoreLabLogic)
    const inputReason = inputDisabledReason(editorInputMode, editorInputFields, editorInputQuery)
    const outputReason = outputFieldsDisabledReason(editorOutputFields)

    return (
        <div className="flex flex-wrap items-end gap-2">
            <div>
                <label className="text-xs font-semibold" htmlFor="score-lab-sample-size">
                    Sample size
                </label>
                <LemonInput
                    id="score-lab-sample-size"
                    type="number"
                    min={1}
                    max={growthScoreLabRunCreateBodySampleMax}
                    value={sampleSize}
                    onChange={(value) => setSampleSize(value ?? 1)}
                />
            </div>
            <div className="flex-1">
                <label className="text-xs font-semibold" htmlFor="score-lab-contains-filter">
                    Contains
                </label>
                <LemonInput
                    id="score-lab-contains-filter"
                    placeholder="Filter by company or org name"
                    value={containsFilter}
                    onChange={setContainsFilter}
                    disabled={editorInputMode === 'query'}
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
                data-attr="score-lab-run"
            >
                Run
            </LemonButton>
        </div>
    )
}

function ScoreLabSaveControls(): JSX.Element {
    const {
        saveResultLoading,
        selectedLabel,
        isRunning,
        editorInputMode,
        editorInputFields,
        editorInputQuery,
        editorOutputFields,
    } = useValues(scoreLabLogic)
    const { saveVersion } = useActions(scoreLabLogic)
    const inputReason = inputDisabledReason(editorInputMode, editorInputFields, editorInputQuery)
    const outputReason = outputFieldsDisabledReason(editorOutputFields)

    return (
        <div className="flex items-center gap-2">
            <LemonButton
                type="secondary"
                loading={saveResultLoading}
                disabledReason={
                    isRunning
                        ? 'Run in progress'
                        : !selectedLabel
                          ? 'Select a label first'
                          : inputReason
                            ? `${inputReason} before saving`
                            : outputReason
                              ? `${outputReason} before saving`
                              : undefined
                }
                onClick={() => saveVersion()}
                data-attr="score-lab-save"
            >
                Save as new version
            </LemonButton>
            <span className="text-secondary text-xs">
                Freezes the current prompt, model, and inputs. The version number is assigned for you.
            </span>
        </div>
    )
}

function ScoreLabEditor(): JSX.Element {
    return (
        <div className="flex gap-4">
            <div className="min-w-0 flex-1 space-y-4">
                <ScoreLabVersionPicker />
                <ScoreLabEditorPanel />
                <ScoreLabRunControls />
                <ScoreLabSaveControls />
                <ScoreLabResultsTable />
            </div>
        </div>
    )
}

export function ScoreLabScene(): JSX.Element {
    const { user } = useValues(userLogic)
    const { selectedLabel } = useValues(scoreLabLogic)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="This page is only accessible to staff users." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Score lab"
                description="Iterate on enrichment classifier prompts against recently archived orgs, then save and activate a new version."
                resourceType={{ type: 'llm_analytics' }}
            />
            {selectedLabel ? <ScoreLabEditor /> : <ScoreLabLabelPicker />}
        </SceneContent>
    )
}
