import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'

import { WorkflowLogicProps, workflowLogic } from '../../../workflowLogic'
import { HogFlowAction } from '../../types'
import type { stepViewLogicType } from './stepViewLogicType'

export type StepViewLogicProps = {
    action: HogFlowAction
    workflowLogicProps: WorkflowLogicProps
}

export const stepViewLogic = kea<stepViewLogicType>([
    path((key) => [
        'products',
        'workflows',
        'frontend',
        'Workflows',
        'hogflows',
        'steps',
        'components',
        'stepViewLogic',
        key,
    ]),
    props({} as StepViewLogicProps),
    key(({ action }: StepViewLogicProps) => action.id),
    connect(({ workflowLogicProps }: StepViewLogicProps) => ({
        actions: [workflowLogic(workflowLogicProps), ['setWorkflowAction']],
    })),
    actions({
        startEditingName: true,
        startEditingDescription: true,
        setEditNameValue: (value: string) => ({ value }),
        setEditDescriptionValue: (value: string) => ({ value }),
        saveName: true,
        saveDescription: true,
        cancelEditingName: true,
        cancelEditingDescription: true,
    }),
    reducers(({ props }) => ({
        isEditingName: [
            false,
            {
                startEditingName: () => true,
                saveName: () => false,
                cancelEditingName: () => false,
            },
        ],
        isEditingDescription: [
            false,
            {
                startEditingDescription: () => true,
                saveDescription: () => false,
                cancelEditingDescription: () => false,
            },
        ],
        editNameValue: [
            props.action.name,
            {
                setEditNameValue: (_, { value }) => value,
                saveName: (state) => state,
                cancelEditingName: () => props.action.name,
            },
        ],
        editDescriptionValue: [
            props.action.description || '',
            {
                setEditDescriptionValue: (_, { value }) => value,
                saveDescription: (state) => state,
                cancelEditingDescription: () => props.action.description || '',
            },
        ],
    })),
    listeners(({ actions, props, values }) => ({
        saveName: () => {
            const trimmedName = values.editNameValue.trim()
            if (trimmedName && trimmedName !== props.action.name) {
                actions.setWorkflowAction(props.action.id, {
                    ...props.action,
                    name: trimmedName,
                })
            }
        },
        saveDescription: () => {
            const trimmedDescription = values.editDescriptionValue.trim()
            if (trimmedDescription && trimmedDescription !== (props.action.description || '')) {
                actions.setWorkflowAction(props.action.id, {
                    ...props.action,
                    description: trimmedDescription,
                })
            }
        },
    })),
    propsChanged(({ actions, props, values }) => {
        if (!values.isEditingName && values.editNameValue !== props.action.name) {
            actions.setEditNameValue(props.action.name)
        }
        if (!values.isEditingDescription && values.editDescriptionValue !== (props.action.description || '')) {
            actions.setEditDescriptionValue(props.action.description || '')
        }
    }),
])
