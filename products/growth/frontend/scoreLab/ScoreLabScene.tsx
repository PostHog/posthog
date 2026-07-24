import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonDialog,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { TZLabel } from 'lib/components/TZLabel'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { ConfigVersionApi, LabelSummaryApi } from '../generated/api.schemas'
import { GrowthScoreLabModelEnumApi } from '../generated/api.schemas'
import { SCORE_LAB_INPUT_FIELD_OPTIONS } from './scoreLabInputFields'
import { SCORE_LAB_MAX_SAMPLE_SIZE, scoreLabLogic } from './scoreLabLogic'
import { ScoreLabResultsTable } from './ScoreLabResultsTable'

export const scene: SceneExport = {
    component: ScoreLabScene,
    logic: scoreLabLogic,
}

const MODEL_OPTIONS = Object.values(GrowthScoreLabModelEnumApi).map((model) => ({ value: model, label: model }))

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

function ScoreLabVersionsRail(): JSX.Element {
    const { versions, configsLoading, selectedVersionId, activateResultLoading } = useValues(scoreLabLogic)
    const { loadVersionIntoEditor, activateVersion } = useActions(scoreLabLogic)

    const columns: LemonTableColumns<ConfigVersionApi> = [
        {
            key: 'version',
            render: (_, version) => (
                <div
                    className={clsx(
                        '-m-1 cursor-pointer rounded p-1',
                        version.id === selectedVersionId && 'bg-accent-highlight-secondary'
                    )}
                    onClick={() => loadVersionIntoEditor(version)}
                >
                    <div className="flex items-center gap-1">
                        <span className="font-semibold">{version.version}</span>
                        {version.is_active && <LemonTag type="success">ACTIVE</LemonTag>}
                    </div>
                    <div className="text-secondary text-xs">
                        {version.created_by_email ?? 'system'} · <TZLabel time={version.created_at} />
                    </div>
                    {version.id === selectedVersionId && !version.is_active && (
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            className="mt-1"
                            loading={activateResultLoading}
                            onClick={(e) => {
                                e.stopPropagation()
                                LemonDialog.open({
                                    title: `Activate version ${version.version}?`,
                                    description:
                                        'The batch runner will start computing this version instead of the currently active one.',
                                    primaryButton: {
                                        children: 'Activate',
                                        onClick: () => activateVersion(version.id),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Activate
                        </LemonButton>
                    )}
                </div>
            ),
        },
    ]

    return (
        <div className="w-80 shrink-0 space-y-2">
            <h4 className="mb-0">Versions</h4>
            <LemonTable
                dataSource={versions}
                loading={configsLoading}
                rowKey={(version) => version.id}
                columns={columns}
                showHeader={false}
                embedded
                emptyState="No versions saved for this label yet."
            />
        </div>
    )
}

function ScoreLabEditorPanel(): JSX.Element {
    const { editorPromptText, editorModel, editorInputFields, isEditorDirty } = useValues(scoreLabLogic)
    const { setEditorPromptText, setEditorModel, toggleEditorInputField } = useActions(scoreLabLogic)

    return (
        <div className="space-y-2">
            {isEditorDirty && <LemonBanner type="info">Editing (unsaved experiment)</LemonBanner>}
            <div className="flex items-center gap-2">
                <span className="font-semibold">Model</span>
                <LemonSelect
                    value={editorModel}
                    onChange={(value) => value && setEditorModel(value)}
                    options={MODEL_OPTIONS}
                />
            </div>
            <CodeEditor
                className="border"
                language="markdown"
                value={editorPromptText}
                onChange={(value) => setEditorPromptText(value ?? '')}
                height={320}
                options={{ minimap: { enabled: false }, wordWrap: 'on' }}
            />
            <div className="space-y-1">
                <span className="font-semibold">Input fields</span>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                    {SCORE_LAB_INPUT_FIELD_OPTIONS.map((option) => (
                        <LemonCheckbox
                            key={option.value}
                            label={option.label}
                            checked={editorInputFields.includes(option.value)}
                            onChange={() => toggleEditorInputField(option.value)}
                        />
                    ))}
                </div>
            </div>
        </div>
    )
}

function ScoreLabRunControls(): JSX.Element {
    const { sampleSize, containsFilter, canRun, isRunning } = useValues(scoreLabLogic)
    const { setSampleSize, setContainsFilter, runClassification } = useActions(scoreLabLogic)

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
                    max={SCORE_LAB_MAX_SAMPLE_SIZE}
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
                />
            </div>
            <LemonButton
                type="primary"
                loading={isRunning}
                disabledReason={!canRun && !isRunning ? 'Enter a prompt before running' : undefined}
                onClick={() => runClassification()}
                data-attr="score-lab-run"
            >
                Run
            </LemonButton>
        </div>
    )
}

function ScoreLabSaveControls(): JSX.Element {
    const { newVersionInput, saveResultLoading, selectedLabel } = useValues(scoreLabLogic)
    const { setNewVersionInput, saveVersion } = useActions(scoreLabLogic)

    return (
        <div className="flex items-end gap-2">
            <div>
                <label className="text-xs font-semibold" htmlFor="score-lab-new-version">
                    New version
                </label>
                <LemonInput
                    id="score-lab-new-version"
                    value={newVersionInput}
                    onChange={setNewVersionInput}
                    placeholder="e.g. ai-pilled-clay-v2"
                />
            </div>
            <LemonButton
                type="secondary"
                loading={saveResultLoading}
                disabledReason={
                    !selectedLabel
                        ? 'Select a label first'
                        : !newVersionInput.trim()
                          ? 'Enter a version name'
                          : undefined
                }
                onClick={() => saveVersion()}
                data-attr="score-lab-save"
            >
                Save as new version
            </LemonButton>
        </div>
    )
}

function ScoreLabEditor(): JSX.Element {
    const { selectedLabel } = useValues(scoreLabLogic)

    return (
        <div className="flex gap-4">
            <ScoreLabVersionsRail />
            <div className="min-w-0 flex-1 space-y-4">
                <h3 className="mb-0">{selectedLabel}</h3>
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
