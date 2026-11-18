import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { NEW_HOLDOUT, holdoutsLogic } from 'scenes/experiments/holdoutsLogic'

import { ExperimentHoldoutType } from '~/types'

export const HOLDOUTS_INTRO =
    'Holdouts are stable groups of users excluded from experiment variations.They act as a baseline, helping you see how users behave without any changes applied. This lets you directly compare their behavior to those exposed to the experiment variations. Once a holdout is configured, you can apply it to an experiment during creation.'
export const HOLDOUT_ROLLOUT_HELP =
    'Specify the percentage population that should be included in this holdout group. This is stable across experiments.'
export const HOLDOUTS_EMPTY = 'You have not created any holdouts yet.'
export const HOLDOUT_NAME_PLACEHOLDER = "e.g. 'Frontend holdout group 1'"
export const DELETE_HOLDOUT_TITLE = 'Delete this holdout?'

export interface HoldoutsSceneModel {
    holdouts: ExperimentHoldoutType[]
    holdoutsLoading: boolean
    holdout: ExperimentHoldoutType
    setHoldout: (holdout: Partial<ExperimentHoldoutType>) => void
    isModalOpen: boolean
    editingHoldout: ExperimentHoldoutType | null
    openEditModal: (holdout: ExperimentHoldoutType) => void
    openCreateModal: () => void
    closeModal: () => void
    save: () => void
    saveDisabledReason?: string
    rolloutPercentage: number
    setRolloutPercentage: (rollout_percentage: number | undefined) => void
    deleteHoldout: (id: ExperimentHoldoutType['id']) => void
}

export function useHoldoutsScene(): HoldoutsSceneModel {
    const { holdouts, holdoutsLoading, holdout } = useValues(holdoutsLogic)
    const { createHoldout, deleteHoldout, setHoldout, updateHoldout } = useActions(holdoutsLogic)

    const [isModalOpen, setIsModalOpen] = useState(false)
    const [editingHoldout, setEditingHoldout] = useState<ExperimentHoldoutType | null>(null)

    const closeModal = (): void => {
        setIsModalOpen(false)
        setEditingHoldout(null)
    }

    const rollout = holdout.filters?.[0]?.rollout_percentage

    return {
        holdouts,
        holdoutsLoading,
        holdout,
        setHoldout,
        isModalOpen,
        editingHoldout,
        openEditModal: (next) => {
            setEditingHoldout(next)
            setHoldout(next)
            setIsModalOpen(true)
        },
        openCreateModal: () => {
            setEditingHoldout(null)
            setHoldout({ ...NEW_HOLDOUT })
            setIsModalOpen(true)
        },
        closeModal,
        save: () => {
            if (editingHoldout) {
                updateHoldout(editingHoldout.id, holdout)
            } else {
                createHoldout()
            }
            closeModal()
        },
        saveDisabledReason: !holdout.name
            ? 'Name is required'
            : rollout === undefined || rollout === null
              ? 'Rollout percentage is required'
              : rollout < 0 || rollout > 100
                ? 'Rollout percentage should be between 0 and 100'
                : undefined,
        rolloutPercentage: rollout || 100,
        setRolloutPercentage: (rollout_percentage) =>
            setHoldout({ filters: [{ properties: [], rollout_percentage: rollout_percentage as number }] }),
        deleteHoldout: (id) => {
            if (id !== null) {
                deleteHoldout(id)
            }
        },
    }
}
