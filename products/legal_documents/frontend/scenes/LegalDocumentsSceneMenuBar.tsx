import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { LegalDocumentType } from './legalDocumentsLogic'
import { QuillNewLegalDocumentMenu } from './QuillNewLegalDocumentMenu'

const RESOURCE_TYPE = 'legal-documents'

interface LegalDocumentsSceneMenuBarProps {
    existingDocumentTypes: Set<LegalDocumentType>
    baaBlockedReason?: string
}

export function LegalDocumentsSceneMenuBar(props: LegalDocumentsSceneMenuBarProps): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <LegalDocumentsSceneMenuBarInner {...props} /> : null
}

function LegalDocumentsSceneMenuBarInner({
    existingDocumentTypes,
    baaBlockedReason,
}: LegalDocumentsSceneMenuBarProps): JSX.Element {
    const alreadyExistsReason = (type: LegalDocumentType): string | undefined =>
        existingDocumentTypes.has(type)
            ? `Your organization already has a ${type}. Contact support if you need a new one.`
            : undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            type: 'submenu',
            id: `${RESOURCE_TYPE}-menubar-new`,
            label: 'New',
            icon: <IconPlusSmall />,
            tooltip: 'Generate a new legal document',
            items: [
                {
                    id: `${RESOURCE_TYPE}-menubar-new-dpa`,
                    label: 'Data Processing Agreement (DPA)',
                    disabledReason: alreadyExistsReason('DPA'),
                    onSelect: () => router.actions.push(urls.legalDocumentNew('DPA')),
                },
                {
                    id: `${RESOURCE_TYPE}-menubar-new-baa`,
                    label: 'Business Associate Agreement (BAA)',
                    disabledReason: alreadyExistsReason('BAA') ?? baaBlockedReason,
                    onSelect: () => router.actions.push(urls.legalDocumentNew('BAA')),
                },
                {
                    id: `${RESOURCE_TYPE}-menubar-new-msa`,
                    label: 'Master Service Agreement (MSA)',
                    disabledReason: 'MSAs are negotiated by sales. Contact your TAM or PostHog support to sign an MSA.',
                    onSelect: () => {},
                },
            ],
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => (
                    <QuillNewLegalDocumentMenu
                        existingDocumentTypes={existingDocumentTypes}
                        baaBlockedReason={baaBlockedReason}
                    />
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
