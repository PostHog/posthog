import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { openSaveToModal } from 'lib/components/SaveTo/saveToLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { performQuery } from '~/queries/query'
import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    Breadcrumb,
    EarlyAccessFeatureStage,
    EarlyAccessFeatureTabs,
    EarlyAccessFeatureType,
    NewEarlyAccessFeatureType,
    ProjectTreeRef,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import type { earlyAccessFeatureLogicType } from './earlyAccessFeatureLogicType'
import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'
export const NEW_EARLY_ACCESS_FEATURE: NewEarlyAccessFeatureType = {
    name: '',
    description: '',
    stage: EarlyAccessFeatureStage.Draft,
    documentation_url: '',
    feature_flag_id: undefined,
}

export interface EarlyAccessFeatureLogicProps {
    /** Either a UUID or "new". */
    id: string
}

export const earlyAccessFeatureLogic = kea<earlyAccessFeatureLogicType>([
    path(['products', 'earlyAccessFeatures', 'frontend', 'earlyAccessFeatureLogic']),
    props({} as EarlyAccessFeatureLogicProps),
    key(({ id }) => id),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], earlyAccessFeaturesLogic, ['earlyAccessFeatures']],
        actions: [earlyAccessFeaturesLogic, ['loadEarlyAccessFeatures', 'loadEarlyAccessFeaturesSuccess']],
    })),
    actions({
        setEarlyAccessFeatureMissing: true,
        toggleImplementOptInInstructionsModal: true,
        editFeature: (editing: boolean) => ({ editing }),
        updateStage: (stage: EarlyAccessFeatureStage) => ({ stage }),
        deleteEarlyAccessFeature: (earlyAccessFeatureId: EarlyAccessFeatureType['id']) => ({ earlyAccessFeatureId }),
        setActiveTab: (activeTab: EarlyAccessFeatureTabs) => ({ activeTab }),
    }),
    loaders(({ props, values, actions }) => ({
        earlyAccessFeature: {
            loadEarlyAccessFeature: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const response = await api.earlyAccessFeatures.get(props.id)
                        return response
                    } catch (error: any) {
                        actions.setEarlyAccessFeatureMissing()
                        throw error
                    }
                }
                return NEW_EARLY_ACCESS_FEATURE
            },
            saveEarlyAccessFeature: async (
                updatedEarlyAccessFeature: Partial<EarlyAccessFeatureType | NewEarlyAccessFeatureType>
            ) => {
                let result: EarlyAccessFeatureType
                if (props.id === 'new') {
                    result = await api.earlyAccessFeatures.create(
                        updatedEarlyAccessFeature as NewEarlyAccessFeatureType
                    )
                    router.actions.replace(urls.earlyAccessFeature(result.id))
                } else {
                    result = await api.earlyAccessFeatures.update(
                        props.id,
                        updatedEarlyAccessFeature as EarlyAccessFeatureType
                    )
                }
                return result
            },
        },

        personsCount: [
            null as [number, number] | null,
            {
                loadEarlyAccessFeatureSuccess: async (_, breakpoint) => {
                    // Should exist because it was a success, but Typescript doesn't know that
                    if (!values.earlyAccessFeature || !('feature_flag' in values.earlyAccessFeature)) {
                        return null
                    }

                    // :KRUDGE: Should try and get this to work with a single query in the future
                    const results = await Promise.all(
                        ['true', 'false'].map((value) =>
                            performQuery<ActorsQuery>({
                                kind: NodeKind.ActorsQuery,
                                properties: [
                                    {
                                        key: values.featureEnrollmentKey,
                                        type: PropertyFilterType.Person,
                                        operator: PropertyOperator.Exact,
                                        value: [value],
                                    },
                                ],
                                select: ['count()'],
                            })
                        )
                    )
                    breakpoint()

                    return results.map((result) => result?.results?.[0]?.[0] ?? null) as [number, number]
                },
            },
        ],
    })),
    forms(({ actions, props }) => ({
        earlyAccessFeature: {
            defaults: { ...NEW_EARLY_ACCESS_FEATURE } as NewEarlyAccessFeatureType | EarlyAccessFeatureType,
            errors: (payload) => ({
                name: !payload.name ? 'Feature name must be set' : undefined,
            }),
            submit: async (payload) => {
                if (props.id && props.id !== 'new') {
                    actions.saveEarlyAccessFeature(payload)
                } else {
                    openSaveToModal({
                        defaultFolder: 'Unfiled/Early Access Features',
                        callback: (folder) => actions.saveEarlyAccessFeature({ ...payload, _create_in_folder: folder }),
                    })
                }
            },
        },
    })),
    reducers({
        earlyAccessFeatureMissing: [
            false,
            {
                setEarlyAccessFeatureMissing: () => true,
            },
        ],
        isEditingFeature: [
            false,
            {
                editFeature: (_, { editing }) => editing,
            },
        ],
        implementOptInInstructionsModal: [
            false,
            {
                toggleImplementOptInInstructionsModal: (state) => !state,
            },
        ],
        activeTab: [
            EarlyAccessFeatureTabs.OptedIn as EarlyAccessFeatureTabs,
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
    }),
    selectors({
        mode: [(_, p) => [p.id], (id): 'view' | 'edit' => (id === 'new' ? 'edit' : 'view')],
        breadcrumbs: [
            (s) => [s.earlyAccessFeature],
            (earlyAccessFeature: EarlyAccessFeatureType): Breadcrumb[] => [
                {
                    key: 'EarlyAccessFeatures',
                    name: 'Early Access Management',
                    path: urls.earlyAccessFeatures(),
                },
                {
                    key: ['EarlyAccessFeature', earlyAccessFeature.id || 'new'],
                    name: earlyAccessFeature.name,
                },
            ],
        ],
        projectTreeRef: [
            () => [(_, props: EarlyAccessFeatureLogicProps) => props.id],
            (id): ProjectTreeRef => ({ type: 'early_access_feature', ref: id === 'new' ? null : String(id) }),
        ],
        optedInCount: [
            (s) => [s.personsCount],
            (personsCount: [number, number] | null): number | null => personsCount?.[0] ?? null,
        ],
        optedOutCount: [
            (s) => [s.personsCount],
            (personsCount: [number, number] | null): number | null => personsCount?.[1] ?? null,
        ],
        featureEnrollmentKey: [
            (s) => [s.earlyAccessFeature],
            (earlyAccessFeature: EarlyAccessFeatureType): string => {
                return '$feature_enrollment/' + earlyAccessFeature.feature_flag.key
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        updateStage: async ({ stage }) => {
            'id' in values.earlyAccessFeature &&
                (await api.earlyAccessFeatures.update(props.id, {
                    ...values.earlyAccessFeature,
                    stage: stage,
                }))
            if (props.id) {
                refreshTreeItem('early_access_feature', props.id)
            }
            actions.loadEarlyAccessFeature()
            actions.loadEarlyAccessFeatures()
        },
        saveEarlyAccessFeatureSuccess: ({ earlyAccessFeature: _earlyAccessFeature }) => {
            lemonToast.success('Early Access Feature saved')
            actions.loadEarlyAccessFeatures()
            _earlyAccessFeature.id && router.actions.replace(urls.earlyAccessFeature(_earlyAccessFeature.id))
            actions.editFeature(false)
        },
        deleteEarlyAccessFeature: async ({ earlyAccessFeatureId }) => {
            try {
                await api.earlyAccessFeatures.delete(earlyAccessFeatureId)
                lemonToast.info(
                    'Early access feature deleted. Remember to delete corresponding feature flag if necessary'
                )
                actions.loadEarlyAccessFeaturesSuccess(
                    values.earlyAccessFeatures.filter((feature) => feature.id !== earlyAccessFeatureId)
                )
                deleteFromTree('early_access_feature', earlyAccessFeatureId)
                router.actions.push(urls.earlyAccessFeatures())
            } catch (e) {
                lemonToast.error(`Error deleting Early Access Feature: ${e}`)
            }
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.earlyAccessFeature(props.id ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadEarlyAccessFeature()
                }
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.id !== 'new') {
            actions.loadEarlyAccessFeature()
        }
    }),
])
