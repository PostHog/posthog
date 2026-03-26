import { useActions, useMountedLogic, useValues } from 'kea'

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

import { updatedAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type {
    Kind01eEnumApi as ScoreDefinitionKind,
    ScoreDefinitionApi as ScoreDefinition,
} from '../generated/api.schemas'
import { llmAnalyticsScoreDefinitionsLogic, SCORE_DEFINITIONS_PER_PAGE } from './llmAnalyticsScoreDefinitionsLogic'
import { scoreDefinitionModalLogic } from './scoreDefinitionModalLogic'
import {
    CATEGORICAL_SELECTION_MODE_OPTIONS,
    formatKindLabel,
    formatNumericInputValue,
    getIntegerInputValue,
    getNumericInputValue,
    type CategoricalSelectionMode,
    type ScoreDefinitionModalMode,
} from './scoreDefinitionModalUtils'

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

export function LLMAnalyticsScoreDefinitions({ tabId }: { tabId?: string }): JSX.Element {
    const logic = useMountedLogic(llmAnalyticsScoreDefinitionsLogic({ tabId }))
    const { setFilters, openModal, closeModal, toggleArchive } = useActions(logic)
    const {
        scoreDefinitions,
        scoreDefinitionsLoading,
        sorting,
        pagination,
        filters,
        scoreDefinitionCountLabel,
        modalMode,
        selectedDefinition,
        isArchivingDefinition,
    } = useValues(logic)
    const modalProps =
        modalMode === null || (modalMode !== 'create' && selectedDefinition === null)
            ? null
            : {
                  mode: modalMode,
                  scoreDefinition: selectedDefinition,
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
                                        onClick={() => toggleArchive(scoreDefinition)}
                                        disabled={isArchivingDefinition(scoreDefinition.id)}
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

            {modalProps && (
                <ScoreDefinitionModal
                    tabId={tabId}
                    mode={modalProps.mode}
                    scoreDefinition={modalProps.scoreDefinition}
                    onClose={closeModal}
                />
            )}
        </div>
    )
}

function ScoreDefinitionModal({
    tabId,
    mode,
    scoreDefinition,
    onClose,
}: {
    tabId?: string
    mode: ScoreDefinitionModalMode
    scoreDefinition: ScoreDefinition | null
    onClose: () => void
}): JSX.Element {
    const logic = useMountedLogic(scoreDefinitionModalLogic({ tabId, mode, scoreDefinition }))
    const { submit, setDraftField, updateOptionLabel, addOption, removeOption } = useActions(logic)
    const { draft, isCreateMode, isMetadataMode, isConfigMode, title, submitting } = useValues(logic)

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
                            <LemonInput value={draft.name} onChange={(value) => setDraftField('name', value)} />
                        </div>

                        {isCreateMode ? (
                            <>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Kind</label>
                                    <LemonSelect<ScoreDefinitionKind>
                                        value={draft.kind}
                                        onChange={(value) =>
                                            setDraftField('kind', (value as ScoreDefinitionKind) || 'categorical')
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
                                onChange={(value) => setDraftField('description', value)}
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
                                                setDraftField(
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
                                                        setDraftField(
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
                                                        setDraftField(
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
                                        onChange={(value) =>
                                            setDraftField('numericMin', formatNumericInputValue(value))
                                        }
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Max</label>
                                    <LemonInput
                                        type="number"
                                        value={getNumericInputValue(draft.numericMax)}
                                        onChange={(value) =>
                                            setDraftField('numericMax', formatNumericInputValue(value))
                                        }
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Increment</label>
                                    <LemonInput
                                        type="number"
                                        value={getNumericInputValue(draft.numericStep)}
                                        onChange={(value) =>
                                            setDraftField('numericStep', formatNumericInputValue(value))
                                        }
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
                                        onChange={(value) => setDraftField('trueLabel', value)}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">False label</label>
                                    <LemonInput
                                        value={draft.falseLabel}
                                        onChange={(value) => setDraftField('falseLabel', value)}
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
                <LemonButton type="primary" onClick={() => submit()} loading={submitting}>
                    {isConfigMode ? 'Create version' : 'Save'}
                </LemonButton>
            </LemonModalFooter>
        </LemonModal>
    )
}
