import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import api from 'lib/api'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { toParams } from 'lib/utils/url'
import { ExperimentFlagKeyInputProps } from 'scenes/experiments/ExperimentFlagKeyInput'
import { slugifyFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { FLAGS_PER_PAGE, FeatureFlagsFilters } from 'scenes/feature-flags/featureFlagsLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { Experiment, FeatureFlagType } from '~/types'

import { experimentsLogic } from 'products/experiments/frontend/scenes/experimentsLogic'

export const DUPLICATE_EXPERIMENT_TITLE = 'Duplicate experiment'
export const COPY_EXPERIMENT_TITLE = 'Copy experiment to project'
export const COPY_EXPERIMENT_DESCRIPTION =
    'The experiment and its feature flag will be copied as a draft. The feature flag will be disabled by default in the target project. If a feature flag with the same key already exists, or you select an existing flag, the release configuration for that flag will not be changed.'
export const SELECT_PROJECT_REASON = 'Select a project'

export function copyNamePlaceholder(experiment: Experiment): string {
    return `${experiment.name} (Copy)`
}

interface FlagKeyState {
    flagKey: string
    setFlagKey: (key: string) => void
    flagKeyManuallyEdited: boolean
    isExistingFlag: boolean
    showReuseFlag: boolean
    setShowReuseFlag: (show: boolean) => void
    handleNameFlagKey: (name: string) => void
    handleFlagKeyChange: (value: string) => void
    selectExistingFlag: (key: string) => void
    resetFlagKey: () => void
}

function useFlagKeyState(): FlagKeyState {
    const [flagKey, setFlagKey] = useState('')
    const [flagKeyManuallyEdited, setFlagKeyManuallyEdited] = useState(false)
    const [isExistingFlag, setIsExistingFlag] = useState(false)
    const [showReuseFlag, setShowReuseFlag] = useState(false)

    return {
        flagKey,
        setFlagKey,
        flagKeyManuallyEdited,
        isExistingFlag,
        showReuseFlag,
        setShowReuseFlag,
        handleNameFlagKey: (name) => {
            if (!flagKeyManuallyEdited) {
                setFlagKey(slugifyFeatureFlagKey(name, { fromTitleInput: true }))
                setIsExistingFlag(false)
            }
        },
        handleFlagKeyChange: (value) => {
            setFlagKeyManuallyEdited(true)
            setIsExistingFlag(false)
            setFlagKey(slugifyFeatureFlagKey(value))
        },
        selectExistingFlag: (key) => {
            setFlagKeyManuallyEdited(true)
            setIsExistingFlag(true)
            setFlagKey(key)
        },
        resetFlagKey: () => {
            setFlagKey('')
            setFlagKeyManuallyEdited(false)
            setIsExistingFlag(false)
            setShowReuseFlag(false)
        },
    }
}

export interface DuplicateExperimentModalState {
    experimentName: string
    handleNameChange: (value: string) => void
    handleDuplicate: () => void
    handleClose: () => void
    flagKeyInputProps: ExperimentFlagKeyInputProps
}

export function useDuplicateExperimentModal(
    experiment: Experiment,
    onClose: () => void
): DuplicateExperimentModalState {
    const {
        featureFlagModalFeatureFlags,
        featureFlagModalFeatureFlagsLoading,
        featureFlagModalFilters,
        featureFlagModalPagination,
    } = useValues(experimentsLogic)
    const { duplicateExperiment, setFeatureFlagModalFilters, resetFeatureFlagModalFilters } =
        useActions(experimentsLogic)

    const [experimentName, setExperimentName] = useState('')
    const flag = useFlagKeyState()

    const handleClose = (): void => {
        resetFeatureFlagModalFilters()
        setExperimentName('')
        flag.resetFlagKey()
        onClose()
    }

    return {
        experimentName,
        handleNameChange: (value) => {
            setExperimentName(value)
            flag.handleNameFlagKey(value)
        },
        handleDuplicate: () => {
            duplicateExperiment({
                id: experiment.id as number,
                featureFlagKey: flag.flagKey || undefined,
                name: experimentName.trim() || undefined,
            })
            handleClose()
        },
        handleClose,
        flagKeyInputProps: {
            flagKey: flag.flagKey,
            onFlagKeyChange: flag.handleFlagKeyChange,
            isExistingFlag: flag.isExistingFlag,
            sourceExperiment: experiment,
            featureFlags: featureFlagModalFeatureFlags,
            featureFlagsLoading: featureFlagModalFeatureFlagsLoading,
            featureFlagFilters: featureFlagModalFilters,
            onFeatureFlagFiltersChange: setFeatureFlagModalFilters,
            featureFlagPagination: featureFlagModalPagination,
            onSelectExistingFlag: flag.selectExistingFlag,
            showReuseFlag: flag.showReuseFlag,
            onToggleReuseFlag: flag.setShowReuseFlag,
        },
    }
}

const DEFAULT_FILTERS: Partial<FeatureFlagsFilters> = { search: undefined, order: undefined, page: 1 }

export interface CopyExperimentToProjectModalState {
    teamOptions: { value: number; label: string }[]
    selectedTeamId: number | null
    handleTeamChange: (id: number | null) => void
    experimentName: string
    handleNameChange: (value: string) => void
    handleCopy: () => void
    handleClose: () => void
    copying: boolean
    flagKeyInputProps: ExperimentFlagKeyInputProps
}

export function useCopyExperimentToProjectModal({
    isOpen,
    onClose,
    experiment,
}: {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}): CopyExperimentToProjectModalState {
    const { copyExperimentToProject } = useActions(experimentsLogic)
    const { experimentsLoading } = useValues(experimentsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    const teamOptions =
        currentOrganization?.teams
            ?.filter((team) => team.id !== currentTeam?.id)
            .map((team) => ({ value: team.id, label: team.name }))
            .sort((a, b) => a.label.localeCompare(b.label)) || []
    const onlyTeamOptionValue = teamOptions.length === 1 ? teamOptions[0].value : null

    const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null)
    const [experimentName, setExperimentName] = useState('')
    const flag = useFlagKeyState()

    const [targetFeatureFlags, setTargetFeatureFlags] = useState<{ results: FeatureFlagType[]; count: number }>({
        results: [],
        count: 0,
    })
    const [targetFlagsLoading, setTargetFlagsLoading] = useState(false)
    const [targetFlagFilters, setTargetFlagFilters] = useState<Partial<FeatureFlagsFilters>>(DEFAULT_FILTERS)
    const selectedTeam = currentOrganization?.teams?.find((team) => team.id === selectedTeamId)

    useEffect(() => {
        if (isOpen && onlyTeamOptionValue !== null && selectedTeamId === null) {
            setSelectedTeamId(onlyTeamOptionValue)
        }
    }, [isOpen, onlyTeamOptionValue, selectedTeamId])

    const fetchTargetFlags = async (projectId: number, filters: Partial<FeatureFlagsFilters>): Promise<void> => {
        setTargetFlagsLoading(true)
        try {
            const params = {
                ...filters,
                limit: FLAGS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * FLAGS_PER_PAGE : 0,
                eligible_for_experiment: true,
            }
            // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use featureFlagsList() from 'products/feature_flags/frontend/generated/api' instead.
            const data = await api.get(`api/projects/${projectId}/feature_flags/?${toParams(params)}`)
            setTargetFeatureFlags(data)
        } finally {
            setTargetFlagsLoading(false)
        }
    }

    useEffect(() => {
        if (selectedTeam?.project_id) {
            void fetchTargetFlags(selectedTeam.project_id, targetFlagFilters)
        }
    }, [selectedTeam?.project_id, targetFlagFilters])

    const handleTeamChange = (id: number | null): void => {
        setSelectedTeamId(id)
        // Reset flag state when switching projects
        flag.resetFlagKey()
        setTargetFlagFilters(DEFAULT_FILTERS)
    }

    const handleClose = (): void => {
        setSelectedTeamId(null)
        setExperimentName('')
        flag.resetFlagKey()
        setTargetFlagFilters(DEFAULT_FILTERS)
        setTargetFeatureFlags({ results: [], count: 0 })
        onClose()
    }

    const currentPage = targetFlagFilters.page || 1
    const hasNextPage = targetFeatureFlags.count > currentPage * FLAGS_PER_PAGE
    const hasPreviousPage = currentPage > 1
    const needsPagination = targetFeatureFlags.count > FLAGS_PER_PAGE

    const targetFlagPagination: PaginationManual = {
        controlled: true,
        pageSize: FLAGS_PER_PAGE,
        currentPage,
        entryCount: targetFeatureFlags.count,
        onForward:
            needsPagination && hasNextPage
                ? () => setTargetFlagFilters((prev) => ({ ...prev, page: (prev.page || 1) + 1 }))
                : undefined,
        onBackward:
            needsPagination && hasPreviousPage
                ? () => setTargetFlagFilters((prev) => ({ ...prev, page: Math.max(1, (prev.page || 1) - 1) }))
                : undefined,
    }

    return {
        teamOptions,
        selectedTeamId,
        handleTeamChange,
        experimentName,
        handleNameChange: (value) => {
            setExperimentName(value)
            flag.handleNameFlagKey(value)
        },
        handleCopy: () => {
            if (selectedTeamId && selectedTeam) {
                copyExperimentToProject({
                    id: experiment.id as number,
                    targetProjectId: selectedTeam.project_id,
                    targetTeamId: selectedTeamId,
                    featureFlagKey: flag.flagKey || undefined,
                    name: experimentName.trim() || undefined,
                    onSuccess: handleClose,
                })
            }
        },
        handleClose,
        copying: experimentsLoading,
        flagKeyInputProps: {
            flagKey: flag.flagKey,
            onFlagKeyChange: flag.handleFlagKeyChange,
            isExistingFlag: flag.isExistingFlag,
            sourceExperiment: experiment,
            featureFlags: targetFeatureFlags,
            featureFlagsLoading: targetFlagsLoading,
            featureFlagFilters: targetFlagFilters,
            onFeatureFlagFiltersChange: (filters) => setTargetFlagFilters((prev) => ({ ...prev, ...filters })),
            featureFlagPagination: targetFlagPagination,
            onSelectExistingFlag: flag.selectExistingFlag,
            showReuseFlag: flag.showReuseFlag,
            onToggleReuseFlag: flag.setShowReuseFlag,
        },
    }
}
