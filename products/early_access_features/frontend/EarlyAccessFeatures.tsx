import { router } from 'kea-router'

import { LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { defineEntityListScene } from 'lib/components/EntityList'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, EarlyAccessFeatureType } from '~/types'

import { AssigneeDisplay, AssigneeResolver } from 'products/error_tracking/frontend/components/Assignee/AssigneeDisplay'

const STAGES_IN_ORDER: Record<EarlyAccessFeatureType['stage'], number> = {
    draft: 0,
    concept: 1,
    alpha: 2,
    beta: 3,
    'general-availability': 4,
    archived: 5,
}

export const scene = defineEntityListScene<EarlyAccessFeatureType>({
    type: 'early_access_feature',
    scene: Scene.EarlyAccessFeatures,
    url: urls.earlyAccessFeatures(),
    productKey: ProductKey.EARLY_ACCESS_FEATURES,
    mode: 'client',
    load: async () => ({ results: (await api.earlyAccessFeatures.list()).results }),
    search: {
        placeholder: 'Search early access features...',
        keys: ['name', 'description', 'stage'],
    },
    nameColumn: {
        render: (feature) => <>{feature.name}</>,
        description: (feature) => feature.description,
        sorter: (a, b) => a.name.localeCompare(b.name),
    },
    columns: [
        {
            title: 'Stage',
            dataIndex: 'stage',
            render: (_, { stage }) => (
                <LemonTag
                    type={stage === 'beta' ? 'warning' : stage === 'general-availability' ? 'success' : 'default'}
                    className="uppercase cursor-default"
                    data-attr="feature-stage"
                >
                    {stage}
                </LemonTag>
            ),
            sorter: (a, b) => STAGES_IN_ORDER[a.stage] - STAGES_IN_ORDER[b.stage],
        },
        {
            title: 'Assignee',
            key: 'assignee',
            render: (_, { assignee }) => (
                <AssigneeResolver assignee={assignee ?? null}>
                    {({ assignee: resolvedAssignee }) => <AssigneeDisplay assignee={resolvedAssignee} size="small" />}
                </AssigneeResolver>
            ),
        },
        createdAtColumn<EarlyAccessFeatureType>(),
    ],
    newButton: {
        label: 'New feature',
        to: urls.earlyAccessFeature('new'),
        'data-attr': 'create-feature',
        shortcutName: 'NewEarlyAccessFeature',
        // Creating an early access feature requires editor access to the resource.
        disabledReason: () =>
            getAccessControlDisabledReason(AccessControlResourceType.EarlyAccessFeature, AccessControlLevel.Editor) ??
            undefined,
    },
    hideTableWhenEmpty: true,
    banner: ({ isEmpty }) => (
        <ProductIntroduction
            productName="Early access features"
            productKey={ProductKey.EARLY_ACCESS_FEATURES}
            thingName="feature"
            description="Allow your users to individually enable or disable features that are in public beta."
            isEmpty={isEmpty}
            docsURL="https://posthog.com/docs/feature-flags/early-access-feature-management"
            action={() => router.actions.push(urls.earlyAccessFeature('new'))}
            className="my-0"
            mcpSurfaceKey="early_access_features.create"
        />
    ),
})
