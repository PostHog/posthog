import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconSend, IconX } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { legalDocumentsLogic } from './legalDocumentsLogic'

const RESOURCE_TYPE = 'legal-document-new'

export function LegalDocumentNewSceneMenuBar({
    submitDisabledReason,
}: {
    submitDisabledReason?: string
}): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? (
        <LegalDocumentNewSceneMenuBarInner submitDisabledReason={submitDisabledReason} />
    ) : null
}

function LegalDocumentNewSceneMenuBarInner({ submitDisabledReason }: { submitDisabledReason?: string }): JSX.Element {
    const { isLegalDocumentSubmitting } = useValues(legalDocumentsLogic)
    const { submitLegalDocument } = useActions(legalDocumentsLogic)

    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'submit',
            id: `${RESOURCE_TYPE}-menubar-send-for-signature`,
            label: 'Send for signature',
            icon: <IconSend />,
            disabledReason: submitDisabledReason,
            onSelect: submitLegalDocument,
        },
        {
            group: 'edit',
            section: 'submit',
            id: `${RESOURCE_TYPE}-menubar-cancel`,
            label: 'Cancel',
            icon: <IconX />,
            disabledReason: isLegalDocumentSubmitting ? 'Your envelope is on its way' : undefined,
            onSelect: () => router.actions.push(urls.legalDocuments()),
            pinned: { order: 1, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
