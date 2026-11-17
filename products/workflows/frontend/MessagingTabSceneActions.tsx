import { useActions, useValues } from 'kea'

import { IconApple, IconAndroid, IconLetter, IconPlus } from '@posthog/icons'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { openEmailDomainSetupPage } from './Channels/EmailDomain/openEmailDomainSetupPage'
import { MessagingTabActions } from './MessagingTabActions'
import type { MessagingNavTabKey } from './messagingTabs'
import { optOutCategoriesLogic } from './OptOuts/optOutCategoriesLogic'
import { newTemplateAgentLogic } from './TemplateLibrary/newTemplateAgentLogic'

interface MessagingTabSceneActionsProps {
    tab: MessagingNavTabKey
    /** Where the Slack authorization flow returns to, so it lands back on the surface it left. */
    channelsUrl: string
    actions: SceneAction[]
    dataAttrKey: string
}

/**
 * Renders a scene's actions plus the create action of a shared messaging tab, the same one `MessagingTabActions`
 * puts in the title row. One component per tab, so a tab mounts only the logic its own action needs.
 */
export function MessagingTabSceneActions(props: MessagingTabSceneActionsProps): JSX.Element {
    if (props.tab === 'library') {
        return <NewTemplateSceneActions {...props} />
    }
    if (props.tab === 'channels') {
        return <NewChannelSceneActions {...props} />
    }
    if (props.tab === 'opt-outs') {
        return <NewCategorySceneActions {...props} />
    }
    return <SceneActions actions={props.actions} dataAttrKey={props.dataAttrKey} />
}

function titleControl(tab: MessagingNavTabKey, channelsUrl: string): () => JSX.Element {
    return () => <MessagingTabActions tab={tab} channelsUrl={channelsUrl} />
}

function NewTemplateSceneActions({
    tab,
    channelsUrl,
    actions,
    dataAttrKey,
}: MessagingTabSceneActionsProps): JSX.Element {
    const { startNewTemplate } = useActions(newTemplateAgentLogic)
    const newTemplate: SceneAction = {
        group: 'file',
        section: 'create',
        id: `${dataAttrKey}-menubar-new-template`,
        label: 'New template',
        icon: <IconPlus />,
        disabledReason:
            getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor) ?? undefined,
        onSelect: startNewTemplate,
        pinned: {
            order: 10,
            variant: 'primary',
            dataAttr: 'new-message-button',
            render: titleControl(tab, channelsUrl),
        },
    }
    return <SceneActions actions={[newTemplate, ...actions]} dataAttrKey={dataAttrKey} />
}

function NewChannelSceneActions({
    tab,
    channelsUrl,
    actions,
    dataAttrKey,
}: MessagingTabSceneActionsProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSetupModal } = useActions(integrationsLogic)
    const newChannelRestrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const newChannel: SceneAction = {
        group: 'file',
        section: 'create',
        type: 'submenu',
        id: `${dataAttrKey}-menubar-new-channel`,
        label: 'New channel',
        icon: <IconPlus />,
        disabledReason: newChannelRestrictedReason ?? undefined,
        items: [
            {
                id: `${dataAttrKey}-menubar-new-channel-email`,
                label: 'Email',
                icon: <IconLetter />,
                onSelect: () => openEmailDomainSetupPage('channels'),
            },
            {
                id: `${dataAttrKey}-menubar-new-channel-slack`,
                label: 'Slack',
                icon: <IconSlack />,
                onSelect: () => {
                    // The Slack OAuth flow leaves the app, so this is a full page load.
                    window.location.href = api.integrations.authorizeUrl({ kind: 'slack', next: channelsUrl })
                },
            },
            {
                id: `${dataAttrKey}-menubar-new-channel-twilio`,
                label: 'Twilio',
                icon: <IconTwilio />,
                opensFloatingUi: true,
                onSelect: () => openSetupModal(undefined, 'twilio'),
            },
            ...(featureFlags[FEATURE_FLAGS.WORKFLOWS_PUSH_NOTIFICATIONS]
                ? [
                      {
                          id: `${dataAttrKey}-menubar-new-channel-firebase`,
                          label: 'Firebase Cloud Messaging',
                          icon: <IconAndroid />,
                          opensFloatingUi: true,
                          onSelect: () => openSetupModal(undefined, 'firebase'),
                      },
                      {
                          id: `${dataAttrKey}-menubar-new-channel-apns`,
                          label: 'Apple Push Notifications',
                          icon: <IconApple />,
                          opensFloatingUi: true,
                          onSelect: () => openSetupModal(undefined, 'apns'),
                      },
                  ]
                : []),
        ],
        pinned: {
            order: 10,
            variant: 'primary',
            dataAttr: 'new-channel-button',
            render: titleControl(tab, channelsUrl),
        },
    }
    return <SceneActions actions={[newChannel, ...actions]} dataAttrKey={dataAttrKey} />
}

function NewCategorySceneActions({
    tab,
    channelsUrl,
    actions,
    dataAttrKey,
}: MessagingTabSceneActionsProps): JSX.Element {
    const { openNewCategoryModal } = useActions(optOutCategoriesLogic)
    const newCategory: SceneAction = {
        group: 'file',
        section: 'create',
        id: `${dataAttrKey}-menubar-new-category`,
        label: 'New category',
        icon: <IconPlus />,
        opensFloatingUi: true,
        onSelect: () => openNewCategoryModal(),
        pinned: {
            order: 10,
            variant: 'primary',
            dataAttr: 'new-optout-category',
            render: titleControl(tab, channelsUrl),
        },
    }
    return <SceneActions actions={[newCategory, ...actions]} dataAttrKey={dataAttrKey} />
}
