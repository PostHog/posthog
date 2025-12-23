import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonInput, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { EarlyAccessFeatureType } from '~/types'

import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'

export const scene: SceneExport = {
    component: EarlyAccessFeatures,
    logic: earlyAccessFeaturesLogic,
    settingSectionId: 'environment-feature-flags',
}

const STAGES_IN_ORDER: Record<EarlyAccessFeatureType['stage'], number> = {
    draft: 0,
    concept: 1,
    alpha: 2,
    beta: 3,
    'general-availability': 4,
    archived: 5,
}

export function EarlyAccessFeatures(): JSX.Element {
    const { filteredEarlyAccessFeatures, earlyAccessFeaturesLoading, searchTerm } = useValues(earlyAccessFeaturesLogic)
    const { setSearchTerm } = useActions(earlyAccessFeaturesLogic)
    const shouldShowEmptyState = filteredEarlyAccessFeatures.length == 0 && !earlyAccessFeaturesLoading && !searchTerm

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.EarlyAccessFeatures].name}
                description={sceneConfigurations[Scene.EarlyAccessFeatures].description}
                resourceType={{
                    type: sceneConfigurations[Scene.EarlyAccessFeatures].iconType || 'default_icon_type',
                }}
                actions={
                    <AppShortcut
                        name="NewEarlyAccessFeature"
                        keybind={[keyBinds.new]}
                        intent="New early access feature"
                        interaction="click"
                        scope={Scene.EarlyAccessFeatures}
                    >
                        <LemonButton
                            size="small"
                            type="primary"
                            to={urls.earlyAccessFeature('new')}
                            tooltip="New feature"
                        >
                            New feature
                        </LemonButton>
                    </AppShortcut>
                }
            />

            <ProductIntroduction
                productName="Early access features"
                productKey={ProductKey.EARLY_ACCESS_FEATURES}
                thingName="feature"
                description="Allow your users to individually enable or disable features that are in public beta."
                isEmpty={shouldShowEmptyState}
                docsURL="https://posthog.com/docs/feature-flags/early-access-feature-management"
                action={() => router.actions.push(urls.earlyAccessFeature('new'))}
                className="my-0"
            />
            {!shouldShowEmptyState && (
                <>
                    <div className="mb-4">
                        <LemonInput
                            type="search"
                            placeholder="Search early access features..."
                            value={searchTerm}
                            onChange={setSearchTerm}
                            allowClear
                        />
                    </div>
                    <LemonTable
                        loading={earlyAccessFeaturesLoading}
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render(_, feature) {
                                    return (
                                        <LemonTableLink
                                            title={feature.name}
                                            description={feature.description}
                                            to={urls.earlyAccessFeature(feature.id)}
                                        />
                                    )
                                },
                                sorter: (a, b) => a.name.localeCompare(b.name),
                            },
                            {
                                title: 'Stage',
                                dataIndex: 'stage',
                                render(_, { stage }) {
                                    return (
                                        <LemonTag
                                            type={
                                                stage === 'beta'
                                                    ? 'warning'
                                                    : stage === 'general-availability'
                                                      ? 'success'
                                                      : 'default'
                                            }
                                            className="uppercase cursor-default"
                                        >
                                            {stage}
                                        </LemonTag>
                                    )
                                },
                                sorter: (a, b) => STAGES_IN_ORDER[a.stage] - STAGES_IN_ORDER[b.stage],
                            },
                        ]}
                        dataSource={filteredEarlyAccessFeatures}
                        emptyState={
                            searchTerm ? (
                                <div className="text-center py-8">No early access features match your search</div>
                            ) : undefined
                        }
                    />
                </>
            )}
        </SceneContent>
    )
}
