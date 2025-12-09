import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { syntheticUsersSceneLogicType } from './syntheticUsersSceneLogicType'
import { Study, StudyFormValues } from './types'

export const syntheticUsersSceneLogic = kea<syntheticUsersSceneLogicType>([
    path(['products', 'synthetic-users', 'frontend', 'syntheticUsersSceneLogic']),

    actions({
        setShowCreateStudyModal: (show: boolean) => ({ show }),
    }),

    reducers({
        showCreateStudyModal: [
            false,
            {
                setShowCreateStudyModal: (_, { show }) => show,
            },
        ],
    }),

    loaders(() => ({
        studies: [
            [] as Study[],
            {
                loadStudies: async () => {
                    const response = await api.syntheticUsers.getStudies()
                    return response.studies
                },
            },
        ],
        createdStudy: [
            null as Study | null,
            {
                createStudy: async (formValues: StudyFormValues) => {
                    const response = await api.syntheticUsers.createStudy(formValues)
                    return response.study
                },
            },
        ],
    })),

    forms(({ actions }) => ({
        studyForm: {
            defaults: {
                name: '',
                audience_description: '',
                research_goal: '',
                target_url: '',
            } as StudyFormValues,
            errors: ({ name, audience_description, research_goal, target_url }) => ({
                name: !name?.trim() ? 'Study name is required' : undefined,
                audience_description: !audience_description?.trim() ? 'Audience description is required' : undefined,
                research_goal: !research_goal?.trim() ? 'Research goal is required' : undefined,
                target_url: !target_url?.trim() ? 'Target URL is required' : undefined,
            }),
            submit: async (formValues) => {
                actions.createStudy(formValues)
            },
        },
    })),

    listeners(({ actions }) => ({
        createStudySuccess: () => {
            lemonToast.success('Study created')
            actions.resetStudyForm()
            actions.setShowCreateStudyModal(false)
            actions.loadStudies()
        },
        createStudyFailure: ({ error }) => {
            lemonToast.error(`Failed to create study: ${error}`)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStudies()
    }),
])
