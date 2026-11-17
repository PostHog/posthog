import { useValues } from 'kea'

import { IconExternal, IconTrash } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { useAddToNotebookAction } from 'scenes/notebooks/useAddToNotebookAction'
import { userLogic } from 'scenes/userLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { useTodayPeoplePinAction } from '~/layout/today/useTodayPeoplePinAction'
import { PersonType } from '~/types'

import { QuillComposeTicketButton } from 'products/conversations/frontend/components/ComposeTicket/QuillComposeTicketButton'
import { useComposeTicketAction } from 'products/conversations/frontend/components/ComposeTicket/useComposeTicketAction'
import { feedbackSceneAction } from 'products/customer_analytics/frontend/components/feedbackSceneAction'

import { openInAdminPanelDisabledReason, openPersonInAdminPanel } from './openPersonInAdminPanel'

const RESOURCE_TYPE = 'person'
// pinned: the feedback survey targets this element id
const FEEDBACK_BUTTON_ID = 'customer-analytics-person-profile-feedback-button'

interface PersonSceneMenuBarProps {
    person: PersonType
    primaryDistinctId: string | null
    onDelete: () => void
    deleting: boolean
    onSplitIds: () => void
}

export function PersonSceneMenuBar(props: PersonSceneMenuBarProps): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <PersonSceneMenuBarInner {...props} /> : null
}

function PersonSceneMenuBarInner({
    person,
    primaryDistinctId,
    onDelete,
    deleting,
    onSplitIds,
}: PersonSceneMenuBarProps): JSX.Element {
    const { user } = useValues(userLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const distinctId = primaryDistinctId ?? person.distinct_ids[0]
    const email = typeof person.properties?.email === 'string' ? person.properties.email : undefined
    const newTicketAction = useComposeTicketAction(RESOURCE_TYPE, { distinctId, email })
    const addToNotebookAction = useAddToNotebookAction(RESOURCE_TYPE, {
        notebookSelectButtonProps: { resource: { type: NotebookNodeType.Person, attrs: { id: person.uuid } } },
    })
    const pinActions = useTodayPeoplePinAction()

    const actions: SceneAction[] = [
        {
            ...newTicketAction,
            pinned: {
                order: 2,
                variant: 'secondary',
                render: () => <QuillComposeTicketButton type="secondary" distinctId={distinctId} email={email} />,
            },
        },
        // The rail redesign drops adding to notebooks from outside a notebook, as the title button does.
        ...(!todayRailNav ? [addToNotebookAction] : []),
        feedbackSceneAction(RESOURCE_TYPE, FEEDBACK_BUTTON_ID),
        {
            group: 'file',
            section: 'delete',
            id: `${RESOURCE_TYPE}-menubar-delete`,
            label: 'Delete person',
            icon: <IconTrash />,
            destructive: true,
            disabledReason: deleting ? 'Deleting this person' : undefined,
            onSelect: onDelete,
        },
        ...pinActions,
        ...(person.distinct_ids.length > 1
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-split-ids`,
                      label: 'Split IDs',
                      opensFloatingUi: true,
                      onSelect: onSplitIds,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(user?.is_staff
            ? ([
                  {
                      group: 'staff',
                      id: `${RESOURCE_TYPE}-menubar-open-in-admin-panel`,
                      label: 'Open in admin panel',
                      icon: <IconExternal />,
                      disabledReason: openInAdminPanelDisabledReason(person),
                      onSelect: () => void openPersonInAdminPanel(person),
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
