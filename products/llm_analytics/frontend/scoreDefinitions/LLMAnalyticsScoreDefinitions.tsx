import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useState } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'

import { ApiConfig } from '~/lib/api'
import { updatedAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    llmAnalyticsScoreDefinitionsCreate,
    llmAnalyticsScoreDefinitionsNewVersionCreate,
    llmAnalyticsScoreDefinitionsPartialUpdate,
} from '../generated/api'
import type {
    BooleanScoreDefinitionConfigApi as BooleanScoreDefinitionConfig,
    CategoricalScoreDefinitionConfigApi as CategoricalScoreDefinitionConfig,
    CategoricalScoreOptionApi as ScoreDefinitionOption,
    Kind01eEnumApi as ScoreDefinitionKind,
    NumericScoreDefinitionConfigApi as NumericScoreDefinitionConfig,
    ScoreDefinitionApi as ScoreDefinition,
    ScoreDefinitionConfigApi as ScoreDefinitionConfig,
} from '../generated/api.schemas'
import { llmAnalyticsScoreDefinitionsLogic, SCORE_DEFINITIONS_PER_PAGE } from './llmAnalyticsScoreDefinitionsLogic'

type ScoreDefinitionModalMode = 'create' | 'duplicate' | 'metadata' | 'config'
type CategoricalSelectionMode = 'single' | 'multiple'

interface ScoreDefinitionDraft {
    name: string
    description: string
    kind: ScoreDefinitionKind
    options: ScoreDefinitionOption[]
    selectionMode: CategoricalSelectionMode
    categoricalMinSelections: string
    categoricalMaxSelections: string
    numericMin: string
    numericMax: string
    numericStep: string
    trueLabel: string
    falseLabel: string
}

const KIND_OPTIONS: { label: string; value: ScoreDefinitionKind | '' }[] = [
    { label: 'All kinds', value: '' },
    { label: 'Categorical', value: 'categorical' },
    { label: 'Numeric', value: 'numeric' },
    { label: 'Boolean', value: 'boolean' },
]

const ARCHIVED_OPTIONS: { label: string; value: '' | 'false' | 'true' }[] = [
    { label: 'Active only', value: 'false' },
    { label: 'All scorers', value: '' },
    { label: 'Archived only', value: 'true' },
]
const CATEGORICAL_SELECTION_MODE_OPTIONS: { label: string; value: CategoricalSelectionMode }[] = [
    { label: 'Single select', value: 'single' },
    { label: 'Multi-select', value: 'multiple' },
]
const DEFAULT_BOOLEAN_TRUE_LABEL = 'Good'
const DEFAULT_BOOLEAN_FALSE_LABEL = 'Bad'

function formatKindLabel(kind: ScoreDefinitionKind): string {
    if (kind === 'categorical') {
        return 'Categorical'
    }
    if (kind === 'numeric') {
        return 'Numeric'
    }
    return 'Boolean'
}

function suggestKey(value: string): string {
    return value
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
}

function getCurrentProjectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

function getApiErrorDetail(error: unknown): string | undefined {
    if (error !== null && typeof error === 'object') {
        if ('detail' in error && typeof error.detail === 'string') {
            return error.detail
        }

        if ('data' in error && error.data && typeof error.data === 'object') {
            for (const value of Object.values(error.data as Record<string, unknown>)) {
                if (Array.isArray(value) && typeof value[0] === 'string') {
                    return value[0]
                }
                if (typeof value === 'string') {
                    return value
                }
            }
        }
    }

    return undefined
}

function parseOptionalNumber(value: string): number | null {
    if (!value.trim()) {
        return null
    }

    const parsedValue = Number(value)
    return Number.isFinite(parsedValue) ? parsedValue : NaN
}

function parseOptionalInteger(value: string): number | null {
    if (!value.trim()) {
        return null
    }

    const parsedValue = Number(value)
    return Number.isInteger(parsedValue) ? parsedValue : NaN
}

function getNumericInputValue(value: string): number | undefined {
    const parsedValue = parseOptionalNumber(value)
    return parsedValue === null || Number.isNaN(parsedValue) ? undefined : parsedValue
}

function getIntegerInputValue(value: string): number | undefined {
    const parsedValue = parseOptionalInteger(value)
    return parsedValue === null || Number.isNaN(parsedValue) ? undefined : parsedValue
}

function formatNumericInputValue(value: number | undefined): string {
    return typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
}

function getCategoricalConfig(config: ScoreDefinitionConfig): CategoricalScoreDefinitionConfig {
    return 'options' in config ? { selection_mode: 'single', ...config } : { options: [], selection_mode: 'single' }
}

function getNumericConfig(config: ScoreDefinitionConfig): NumericScoreDefinitionConfig {
    return 'min' in config || 'max' in config || 'step' in config ? config : {}
}

function getBooleanConfig(config: ScoreDefinitionConfig): BooleanScoreDefinitionConfig {
    return 'true_label' in config || 'false_label' in config ? config : {}
}

function createDraft(mode: ScoreDefinitionModalMode, scoreDefinition?: ScoreDefinition | null): ScoreDefinitionDraft {
    const baseDefinition = scoreDefinition || null
    const kind = baseDefinition?.kind || 'categorical'
    const categoricalConfig: CategoricalScoreDefinitionConfig = baseDefinition
        ? getCategoricalConfig(baseDefinition.config)
        : { options: [], selection_mode: 'single' }
    const numericConfig = baseDefinition ? getNumericConfig(baseDefinition.config) : {}
    const booleanConfig = baseDefinition ? getBooleanConfig(baseDefinition.config) : {}

    const defaultOptions =
        categoricalConfig.options.length > 0
            ? categoricalConfig.options.map((option) => ({ ...option }))
            : [
                  { key: 'good', label: 'Good' },
                  { key: 'bad', label: 'Bad' },
              ]

    const duplicatedName = baseDefinition ? `${baseDefinition.name} copy` : ''

    return {
        name: mode === 'duplicate' ? duplicatedName : baseDefinition?.name || '',
        description: baseDefinition?.description || '',
        kind,
        options: defaultOptions,
        selectionMode: categoricalConfig.selection_mode || 'single',
        categoricalMinSelections:
            categoricalConfig.min_selections === undefined || categoricalConfig.min_selections === null
                ? ''
                : String(categoricalConfig.min_selections),
        categoricalMaxSelections:
            categoricalConfig.max_selections === undefined || categoricalConfig.max_selections === null
                ? ''
                : String(categoricalConfig.max_selections),
        numericMin: numericConfig.min === undefined || numericConfig.min === null ? '' : String(numericConfig.min),
        numericMax: numericConfig.max === undefined || numericConfig.max === null ? '' : String(numericConfig.max),
        numericStep: numericConfig.step === undefined || numericConfig.step === null ? '' : String(numericConfig.step),
        trueLabel: booleanConfig.true_label || DEFAULT_BOOLEAN_TRUE_LABEL,
        falseLabel: booleanConfig.false_label || DEFAULT_BOOLEAN_FALSE_LABEL,
    }
}

function buildConfigFromDraft(draft: ScoreDefinitionDraft): ScoreDefinitionConfig {
    if (draft.kind === 'categorical') {
        const categoricalConfig: CategoricalScoreDefinitionConfig = {
            options: draft.options.map((option) => ({
                key: option.key.trim() || suggestKey(option.label),
                label: option.label.trim(),
            })),
        }

        if (draft.selectionMode === 'multiple') {
            categoricalConfig.selection_mode = 'multiple'

            const minimum = parseOptionalInteger(draft.categoricalMinSelections)
            const maximum = parseOptionalInteger(draft.categoricalMaxSelections)

            if (minimum !== null) {
                categoricalConfig.min_selections = minimum
            }

            if (maximum !== null) {
                categoricalConfig.max_selections = maximum
            }
        }

        return categoricalConfig
    }

    if (draft.kind === 'numeric') {
        const numericConfig: NumericScoreDefinitionConfig = {}
        const minimum = parseOptionalNumber(draft.numericMin)
        const maximum = parseOptionalNumber(draft.numericMax)
        const step = parseOptionalNumber(draft.numericStep)

        if (minimum !== null) {
            numericConfig.min = minimum
        }
        if (maximum !== null) {
            numericConfig.max = maximum
        }
        if (step !== null) {
            numericConfig.step = step
        }

        return numericConfig
    }

    const booleanConfig: BooleanScoreDefinitionConfig = {}
    if (draft.trueLabel.trim()) {
        booleanConfig.true_label = draft.trueLabel.trim()
    }
    if (draft.falseLabel.trim()) {
        booleanConfig.false_label = draft.falseLabel.trim()
    }
    return booleanConfig
}

function validateDraft(mode: ScoreDefinitionModalMode, draft: ScoreDefinitionDraft): string | undefined {
    if (mode !== 'config') {
        if (!draft.name.trim()) {
            return 'Name is required.'
        }
    }

    if (draft.kind === 'categorical') {
        if (draft.options.length === 0) {
            return 'Add at least one categorical option.'
        }

        const optionLabels = new Set<string>()
        const optionKeys = new Set<string>()
        for (const option of draft.options) {
            const normalizedLabel = option.label.trim()
            if (!normalizedLabel) {
                return 'Each categorical option needs a label.'
            }
            const normalizedLabelKey = normalizedLabel.toLowerCase()
            if (optionLabels.has(normalizedLabelKey)) {
                return 'Categorical option labels must be unique.'
            }
            optionLabels.add(normalizedLabelKey)

            const normalizedKey = option.key.trim() || suggestKey(normalizedLabel)
            if (!normalizedKey) {
                return 'Categorical option labels must include letters or numbers.'
            }
            if (optionKeys.has(normalizedKey)) {
                return 'Some option labels are too similar and would generate duplicate IDs. Please use more distinct labels.'
            }
            optionKeys.add(normalizedKey)
        }

        if (draft.selectionMode === 'multiple') {
            const selectionValues = [draft.categoricalMinSelections, draft.categoricalMaxSelections]
            if (selectionValues.some((value) => value.trim() && Number.isNaN(parseOptionalInteger(value)))) {
                return 'Selection bounds must be whole numbers.'
            }

            const minimum = parseOptionalInteger(draft.categoricalMinSelections)
            const maximum = parseOptionalInteger(draft.categoricalMaxSelections)

            if (minimum !== null && minimum > draft.options.length) {
                return 'Minimum selections cannot exceed the number of options.'
            }

            if (maximum !== null && maximum > draft.options.length) {
                return 'Maximum selections cannot exceed the number of options.'
            }

            if (minimum !== null && maximum !== null && minimum > maximum) {
                return 'Maximum selections must be greater than or equal to minimum selections.'
            }
        }
    }

    if (draft.kind === 'numeric') {
        const numericValues = [draft.numericMin, draft.numericMax, draft.numericStep]
        if (numericValues.some((value) => value.trim() && Number.isNaN(parseOptionalNumber(value)))) {
            return 'Numeric bounds must be valid numbers.'
        }
    }

    return undefined
}

export function LLMAnalyticsScoreDefinitions({ tabId }: { tabId?: string }): JSX.Element {
    const logic = useMountedLogic(llmAnalyticsScoreDefinitionsLogic({ tabId }))
    const { setFilters, loadScoreDefinitions } = useActions(logic)
    const { scoreDefinitions, scoreDefinitionsLoading, sorting, pagination, filters, scoreDefinitionCountLabel } =
        useValues(logic)

    const [modalMode, setModalMode] = useState<ScoreDefinitionModalMode | null>(null)
    const [selectedDefinition, setSelectedDefinition] = useState<ScoreDefinition | null>(null)

    const closeModal = (): void => {
        setModalMode(null)
        setSelectedDefinition(null)
    }

    const openModal = (mode: ScoreDefinitionModalMode, scoreDefinition?: ScoreDefinition): void => {
        setSelectedDefinition(scoreDefinition || null)
        setModalMode(mode)
    }

    const handleArchiveToggle = async (scoreDefinition: ScoreDefinition): Promise<void> => {
        try {
            await llmAnalyticsScoreDefinitionsPartialUpdate(getCurrentProjectId(), scoreDefinition.id, {
                archived: !scoreDefinition.archived,
            })
            lemonToast.success(scoreDefinition.archived ? 'Scorer unarchived.' : 'Scorer archived.')
            loadScoreDefinitions(false)
        } catch (error) {
            lemonToast.error(getApiErrorDetail(error) || 'Failed to update scorer state.')
        }
    }

    const columns: LemonTableColumns<ScoreDefinition> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '25%',
            render: function renderName(_, scoreDefinition) {
                return (
                    <div className="space-y-1">
                        <div className="font-semibold">{scoreDefinition.name}</div>
                        {scoreDefinition.description ? (
                            <div className="max-w-xl truncate text-muted-alt">{scoreDefinition.description}</div>
                        ) : (
                            <div className="text-muted">No description</div>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Kind',
            dataIndex: 'kind',
            key: 'kind',
            render: function renderKind(kind) {
                return <LemonTag type="muted">{formatKindLabel(kind as ScoreDefinitionKind)}</LemonTag>
            },
        },
        {
            title: 'Version',
            dataIndex: 'current_version',
            key: 'current_version',
            render: function renderVersion(version) {
                return <span className="font-mono text-xs">v{String(version)}</span>
            },
        },
        {
            title: 'Status',
            dataIndex: 'archived',
            key: 'archived',
            render: function renderArchived(archived) {
                return archived ? (
                    <LemonTag type="muted">Archived</LemonTag>
                ) : (
                    <LemonTag type="success">Active</LemonTag>
                )
            },
        },
        updatedAtColumn<ScoreDefinition>() as LemonTableColumn<ScoreDefinition, keyof ScoreDefinition | undefined>,
        {
            width: 0,
            render: function renderActions(_, scoreDefinition) {
                return (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <More
                            overlay={
                                <>
                                    <LemonButton fullWidth onClick={() => openModal('metadata', scoreDefinition)}>
                                        Edit metadata
                                    </LemonButton>
                                    <LemonButton fullWidth onClick={() => openModal('config', scoreDefinition)}>
                                        Edit config
                                    </LemonButton>
                                    <LemonButton fullWidth onClick={() => openModal('duplicate', scoreDefinition)}>
                                        Duplicate
                                    </LemonButton>
                                    <LemonButton
                                        status={scoreDefinition.archived ? 'default' : 'danger'}
                                        fullWidth
                                        onClick={() => void handleArchiveToggle(scoreDefinition)}
                                    >
                                        {scoreDefinition.archived ? 'Unarchive' : 'Archive'}
                                    </LemonButton>
                                </>
                            }
                        />
                    </AccessControlAction>
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 mb-4 border-b justify-between">
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search scorers..."
                        value={filters.search}
                        onChange={(value) => setFilters({ search: value })}
                        className="min-w-64"
                        data-attr="score-definitions-search-input"
                    />
                    <LemonSelect<ScoreDefinitionKind | ''>
                        value={filters.kind}
                        onChange={(value) => setFilters({ kind: value || '' })}
                        options={KIND_OPTIONS}
                    />
                    <LemonSelect<'' | 'false' | 'true'>
                        value={filters.archived}
                        onChange={(value) => setFilters({ archived: value === '' ? '' : value || 'false' })}
                        options={ARCHIVED_OPTIONS}
                    />
                </div>

                <div className="flex items-center gap-2">
                    <div className="text-muted-alt">{scoreDefinitionCountLabel}</div>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => openModal('create')}
                            data-attr="create-score-definition-button"
                        >
                            New scorer
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

            <LemonTable
                loading={scoreDefinitionsLoading}
                columns={columns}
                dataSource={scoreDefinitions.results}
                pagination={pagination}
                noSortingCancellation
                sorting={sorting}
                onSort={(newSorting) =>
                    setFilters({
                        order_by: newSorting
                            ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                            : undefined,
                    })
                }
                rowKey="id"
                loadingSkeletonRows={SCORE_DEFINITIONS_PER_PAGE}
                nouns={['scorer', 'scorers']}
            />

            {modalMode && (
                <ScoreDefinitionModal
                    mode={modalMode}
                    scoreDefinition={selectedDefinition}
                    onClose={closeModal}
                    onSuccess={() => loadScoreDefinitions(false)}
                />
            )}
        </div>
    )
}

function ScoreDefinitionModal({
    mode,
    scoreDefinition,
    onClose,
    onSuccess,
}: {
    mode: ScoreDefinitionModalMode
    scoreDefinition: ScoreDefinition | null
    onClose: () => void
    onSuccess: () => void
}): JSX.Element {
    const [draft, setDraft] = useState<ScoreDefinitionDraft>(() => createDraft(mode, scoreDefinition))
    const [isSubmitting, setIsSubmitting] = useState(false)

    useEffect(() => {
        setDraft(createDraft(mode, scoreDefinition))
    }, [mode, scoreDefinition])

    const isCreateMode = mode === 'create' || mode === 'duplicate'
    const isMetadataMode = mode === 'metadata'
    const isConfigMode = mode === 'config'

    const setField = <K extends keyof ScoreDefinitionDraft>(field: K, value: ScoreDefinitionDraft[K]): void => {
        setDraft((currentDraft) => ({ ...currentDraft, [field]: value }))
    }

    const updateOptionLabel = (index: number, value: string): void => {
        setDraft((currentDraft) => ({
            ...currentDraft,
            options: currentDraft.options.map((option, optionIndex) =>
                optionIndex === index ? { ...option, label: value } : option
            ),
        }))
    }

    const addOption = (): void => {
        setDraft((currentDraft) => ({
            ...currentDraft,
            options: [...currentDraft.options, { key: '', label: '' }],
        }))
    }

    const removeOption = (index: number): void => {
        setDraft((currentDraft) => ({
            ...currentDraft,
            options: currentDraft.options.filter((_, optionIndex) => optionIndex !== index),
        }))
    }

    const handleNameChange = (value: string): void => {
        setDraft((currentDraft) => ({
            ...currentDraft,
            name: value,
        }))
    }

    const handleSubmit = async (): Promise<void> => {
        const validationError = validateDraft(mode, draft)
        if (validationError) {
            lemonToast.error(validationError)
            return
        }

        const config = buildConfigFromDraft(draft)
        const numericConfig = draft.kind === 'numeric' ? (config as NumericScoreDefinitionConfig) : null
        if (
            numericConfig &&
            numericConfig.min != null &&
            numericConfig.max != null &&
            numericConfig.min > numericConfig.max
        ) {
            lemonToast.error('Numeric max must be greater than or equal to min.')
            return
        }

        setIsSubmitting(true)

        try {
            if (isCreateMode) {
                await llmAnalyticsScoreDefinitionsCreate(getCurrentProjectId(), {
                    name: draft.name.trim(),
                    description: draft.description.trim(),
                    kind: draft.kind,
                    config,
                })
                lemonToast.success(mode === 'duplicate' ? 'Scorer duplicated.' : 'Scorer created.')
            } else if (isMetadataMode && scoreDefinition) {
                await llmAnalyticsScoreDefinitionsPartialUpdate(getCurrentProjectId(), scoreDefinition.id, {
                    name: draft.name.trim(),
                    description: draft.description.trim(),
                })
                lemonToast.success('Scorer metadata updated.')
            } else if (isConfigMode && scoreDefinition) {
                await llmAnalyticsScoreDefinitionsNewVersionCreate(getCurrentProjectId(), scoreDefinition.id, {
                    config,
                })
                lemonToast.success('Scorer version created.')
            }

            onSuccess()
            onClose()
        } catch (error) {
            lemonToast.error(getApiErrorDetail(error) || 'Failed to save scorer.')
        } finally {
            setIsSubmitting(false)
        }
    }

    const title =
        mode === 'create'
            ? 'New scorer'
            : mode === 'duplicate'
              ? 'Duplicate scorer'
              : mode === 'metadata'
                ? 'Edit scorer metadata'
                : 'Edit scorer config'

    return (
        <LemonModal isOpen onClose={onClose} simple maxWidth="42rem">
            <LemonModalHeader>
                <h3>{title}</h3>
            </LemonModalHeader>

            <LemonModalContent className="space-y-4">
                {isConfigMode && scoreDefinition ? (
                    <LemonBanner type="info">
                        Saving these config changes creates version v{scoreDefinition.current_version + 1}. Previous
                        versions remain preserved.
                    </LemonBanner>
                ) : null}

                {!isConfigMode ? (
                    <>
                        <div className="space-y-1">
                            <label className="text-sm font-medium">Name</label>
                            <LemonInput value={draft.name} onChange={handleNameChange} />
                        </div>

                        {isCreateMode ? (
                            <>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Kind</label>
                                    <LemonSelect<ScoreDefinitionKind>
                                        value={draft.kind}
                                        onChange={(value) =>
                                            setField('kind', (value as ScoreDefinitionKind) || 'categorical')
                                        }
                                        options={
                                            KIND_OPTIONS.filter((option) => option.value !== '') as {
                                                label: string
                                                value: ScoreDefinitionKind
                                            }[]
                                        }
                                    />
                                </div>
                            </>
                        ) : scoreDefinition ? (
                            <div className="space-y-1">
                                <div className="text-sm font-medium">Kind</div>
                                <div>{formatKindLabel(scoreDefinition.kind)}</div>
                            </div>
                        ) : null}

                        <div className="space-y-1">
                            <label className="text-sm font-medium">Description</label>
                            <LemonTextArea
                                value={draft.description}
                                onChange={(value) => setField('description', value)}
                            />
                        </div>
                    </>
                ) : null}

                {!isMetadataMode ? (
                    <>
                        {draft.kind === 'categorical' ? (
                            <div className="space-y-3">
                                <div className="grid gap-4 sm:grid-cols-3">
                                    <div className="space-y-1">
                                        <label className="text-sm font-medium">Selection mode</label>
                                        <LemonSelect<CategoricalSelectionMode>
                                            value={draft.selectionMode}
                                            onChange={(value) =>
                                                setField(
                                                    'selectionMode',
                                                    (value as CategoricalSelectionMode) || 'single'
                                                )
                                            }
                                            options={CATEGORICAL_SELECTION_MODE_OPTIONS}
                                        />
                                    </div>

                                    {draft.selectionMode === 'multiple' ? (
                                        <>
                                            <div className="space-y-1">
                                                <label className="text-sm font-medium">Min selections</label>
                                                <LemonInput
                                                    type="number"
                                                    value={getIntegerInputValue(draft.categoricalMinSelections)}
                                                    onChange={(value) =>
                                                        setField(
                                                            'categoricalMinSelections',
                                                            formatNumericInputValue(value)
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-sm font-medium">Max selections</label>
                                                <LemonInput
                                                    type="number"
                                                    value={getIntegerInputValue(draft.categoricalMaxSelections)}
                                                    onChange={(value) =>
                                                        setField(
                                                            'categoricalMaxSelections',
                                                            formatNumericInputValue(value)
                                                        )
                                                    }
                                                />
                                            </div>
                                        </>
                                    ) : null}
                                </div>
                                <div className="flex items-center justify-between">
                                    <div className="text-sm font-medium">Options</div>
                                    <LemonButton type="secondary" size="small" onClick={addOption}>
                                        Add option
                                    </LemonButton>
                                </div>
                                <div className="text-xs text-muted-alt">
                                    Enter the labels people should choose from. Internal option IDs are generated
                                    automatically.
                                </div>
                                {draft.options.map((option, index) => (
                                    <div key={`${index}-${option.key}`} className="grid gap-2 sm:grid-cols-[1fr,auto]">
                                        <LemonInput
                                            placeholder="Option label"
                                            value={option.label}
                                            onChange={(value) => updateOptionLabel(index, value)}
                                        />
                                        <LemonButton
                                            type="secondary"
                                            status="danger"
                                            onClick={() => removeOption(index)}
                                            disabledReason={
                                                draft.options.length <= 1 ? 'Keep at least one option' : undefined
                                            }
                                        >
                                            Remove
                                        </LemonButton>
                                    </div>
                                ))}
                            </div>
                        ) : null}

                        {draft.kind === 'numeric' ? (
                            <div className="grid gap-4 sm:grid-cols-3">
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Min</label>
                                    <LemonInput
                                        type="number"
                                        value={getNumericInputValue(draft.numericMin)}
                                        onChange={(value) => setField('numericMin', formatNumericInputValue(value))}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Max</label>
                                    <LemonInput
                                        type="number"
                                        value={getNumericInputValue(draft.numericMax)}
                                        onChange={(value) => setField('numericMax', formatNumericInputValue(value))}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Increment</label>
                                    <LemonInput
                                        type="number"
                                        value={getNumericInputValue(draft.numericStep)}
                                        onChange={(value) => setField('numericStep', formatNumericInputValue(value))}
                                    />
                                    <div className="text-xs text-muted-alt">
                                        Optional amount the score should increase by, for example 1 or 0.5.
                                    </div>
                                </div>
                            </div>
                        ) : null}

                        {draft.kind === 'boolean' ? (
                            <div className="grid gap-4 sm:grid-cols-2">
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">True label</label>
                                    <LemonInput
                                        value={draft.trueLabel}
                                        onChange={(value) => setField('trueLabel', value)}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">False label</label>
                                    <LemonInput
                                        value={draft.falseLabel}
                                        onChange={(value) => setField('falseLabel', value)}
                                    />
                                </div>
                            </div>
                        ) : null}
                    </>
                ) : null}
            </LemonModalContent>

            <LemonModalFooter>
                <LemonButton type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" onClick={() => void handleSubmit()} loading={isSubmitting}>
                    {isConfigMode ? 'Create version' : 'Save'}
                </LemonButton>
            </LemonModalFooter>
        </LemonModal>
    )
}
