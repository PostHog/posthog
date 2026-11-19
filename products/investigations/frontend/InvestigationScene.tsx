import { useActions, useValues } from 'kea'

import { IconEllipsis, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { InvestigationSceneProps, investigationSceneLogic } from './investigationSceneLogic'
import { InvestigationWorkspace } from './InvestigationWorkspace'

export const scene: SceneExport<InvestigationSceneProps> = {
    component: InvestigationScene,
    logic: investigationSceneLogic,
    productKey: ProductKey.INVESTIGATIONS,
    paramsToProps: ({ params }) => ({ id: params.id }),
}

export function InvestigationScene(props: InvestigationSceneProps): JSX.Element {
    const logic = investigationSceneLogic(props)
    const { document, record, loading, busy, dirty, error, conflict } = useValues(logic)
    const { changeDocument, save, saveCopy, archive, loadInvestigation } = useActions(logic)
    const editable = userHasAccess(AccessControlResourceType.Investigation, AccessControlLevel.Editor)
    if (loading) {
        return <Spinner />
    }
    if (!document || !record) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadInvestigation }}>
                {error}
            </LemonBanner>
        )
    }
    return (
        <SceneContent>
            <SceneTitleSection
                name={document.question || 'Untitled investigation'}
                resourceType={{ type: 'investigation', to: urls.investigations() }}
                nameSuffix={<LemonTag>{dirty ? 'Unsaved changes' : 'Saved'}</LemonTag>}
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        {editable && (
                            <LemonButton
                                type="primary"
                                loading={busy}
                                disabledReason={
                                    conflict
                                        ? 'Save a copy or reload the latest version.'
                                        : !dirty
                                          ? 'All changes saved.'
                                          : undefined
                                }
                                onClick={save}
                            >
                                Save
                            </LemonButton>
                        )}
                        <LemonMenu
                            items={[
                                {
                                    label: 'Copy link',
                                    icon: <IconLink />,
                                    onClick: () => copyToClipboard(window.location.href, 'investigation link'),
                                },
                                ...(editable
                                    ? [
                                          {
                                              label: 'Save a copy',
                                              onClick: saveCopy,
                                              disabledReason: busy ? 'Wait for the current save.' : undefined,
                                          },
                                          {
                                              label: 'Archive',
                                              icon: <IconTrash />,
                                              status: 'danger' as const,
                                              disabledReason: busy ? 'Wait for the current save.' : undefined,
                                              onClick: () =>
                                                  LemonDialog.open({
                                                      title: 'Archive this investigation?',
                                                      description:
                                                          'It will be removed from the investigations list. Unsaved changes will be discarded.',
                                                      primaryButton: {
                                                          children: 'Archive',
                                                          status: 'danger',
                                                          onClick: archive,
                                                      },
                                                      secondaryButton: { children: 'Cancel' },
                                                  }),
                                          },
                                      ]
                                    : []),
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} aria-label="More actions" />
                        </LemonMenu>
                    </div>
                }
            />
            {error && (
                <LemonBanner type="error">
                    {error}
                    {conflict && (
                        <div className="flex flex-wrap gap-2 mt-2">
                            <LemonButton type="secondary" onClick={saveCopy} loading={busy}>
                                Save a copy
                            </LemonButton>
                            <LemonButton
                                onClick={() =>
                                    LemonDialog.open({
                                        title: 'Discard your changes and reload?',
                                        description:
                                            'Your unsaved changes will be replaced by the latest saved version.',
                                        primaryButton: { children: 'Reload', onClick: loadInvestigation },
                                        secondaryButton: { children: 'Cancel' },
                                    })
                                }
                            >
                                Reload latest version
                            </LemonButton>
                        </div>
                    )}
                </LemonBanner>
            )}
            <InvestigationWorkspace
                scope={props.id}
                document={document}
                editable={editable}
                onChange={changeDocument}
            />
        </SceneContent>
    )
}
