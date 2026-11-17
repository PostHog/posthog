import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconChat, IconDocument, IconPlus, IconSparkles } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { ScoutChatModal } from './components/config/scouts/ScoutChatModal'
import { useScoutCreateDisabledReason } from './components/config/scouts/ScoutCreateModalHost'
import { ScoutNewButton } from './components/config/scouts/ScoutNewButton'
import { InboxTriageButton, triageLabel } from './components/shell/InboxTriageButton'
import { type ScoutChatType, captureScoutCreatePathChosen } from './inboxAnalytics'
import { inboxSceneLogic } from './inboxSceneLogic'
import { inboxOnboardingLogic } from './logics/inboxOnboardingLogic'
import { reportListLogic, sectionListLogicProps } from './logics/reportListLogic'
import { scoutFleetLogic } from './logics/scoutFleetLogic'
import { scoutSuggestionsLogic } from './logics/scoutSuggestionsLogic'
import { INBOX_PRIMARY_REPORT_SECTION_KEY } from './types'

const RESOURCE_TYPE = 'inbox'

const ASK_PROMPTS: { label: string; chatType: ScoutChatType }[] = [
    { label: 'How is my scout troop performing?', chatType: 'fleet_overview' },
    { label: 'What signals were emitted recently?', chatType: 'recent_signals' },
]

export function InboxSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <InboxSceneMenuBarInner /> : null
}

function InboxSceneMenuBarInner(): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)
    const { onboardingMode } = useValues(inboxOnboardingLogic)
    // Matches the title row: a locked tab offers no actions.
    const tabUnlocked = onboardingMode !== 'takeover' && onboardingMode !== 'pending'
    if (tabUnlocked && activeTab === 'scouts') {
        return <InboxScoutsSceneActions />
    }
    if (tabUnlocked && activeTab === 'reports') {
        return <InboxReportsSceneActions />
    }
    return <SceneActions actions={[]} dataAttrKey={RESOURCE_TYPE} />
}

function InboxReportsSceneActions(): JSX.Element {
    const { count, countIsCapped } = useValues(reportListLogic(sectionListLogicProps(INBOX_PRIMARY_REPORT_SECTION_KEY)))

    const actions: SceneAction[] = [
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-triage`,
            label: triageLabel(count, countIsCapped, false),
            keywords: ['triage'],
            shortcut: 'T',
            disabledReason: count === 0 ? 'No reports in this view need a pull request' : undefined,
            onSelect: () => router.actions.push(urls.inboxTriage()),
            pinned: {
                order: 1,
                variant: 'primary',
                // pinned: autocapture selector. Triage usage insights filter clicks on this data-attr.
                dataAttr: 'inbox-triage-mode',
                render: () => (
                    <div className="hidden @2xl/inbox:contents">
                        <InboxTriageButton />
                    </div>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}

function InboxScoutsSceneActions(): JSX.Element {
    const [chatOpen, setChatOpen] = useState(false)
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { setScoutTemplateDraft } = useActions(inboxSceneLogic)
    const { runningChatType, scoutChatDisabledReason } = useValues(scoutFleetLogic)
    const { loadScoutConfigs, startScoutChatTask } = useActions(scoutFleetLogic)
    const { suggestButtonVisible, hasPicks, isRefreshing, suggestionSetLoading } = useValues(scoutSuggestionsLogic)
    const { askForSuggestions } = useActions(scoutSuggestionsLogic)
    const creationDisabledReason = useScoutCreateDisabledReason() ?? undefined

    const chatDisabledReason =
        scoutChatDisabledReason ?? (runningChatType !== null ? 'Starting another task…' : undefined)
    const askIsStarting = ASK_PROMPTS.some(({ chatType }) => chatType === runningChatType)
    const askDisabledReason =
        runningChatType !== null && !askIsStarting
            ? 'Starting another task…'
            : askIsStarting
              ? 'Starting a task…'
              : (scoutChatDisabledReason ?? undefined)
    // With picks waiting the press only reopens the strip, so nothing else can hold it up.
    const suggestDisabledReason = hasPicks
        ? undefined
        : suggestionSetLoading
          ? 'Reading the suggestions…'
          : isRefreshing
            ? 'Scanning the project…'
            : runningChatType === 'author_scout'
              ? 'Starting a task…'
              : runningChatType !== null
                ? 'Starting another task…'
                : (creationDisabledReason ?? scoutChatDisabledReason ?? undefined)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            type: 'submenu',
            id: `${RESOURCE_TYPE}-menubar-new-scout`,
            label: 'New scout',
            icon: <IconPlus />,
            disabledReason: creationDisabledReason,
            items: [
                {
                    // pinned: data-attr values are wire strings
                    id: 'scout-new-chat',
                    label: 'Chat with an agent',
                    icon: <IconChat />,
                    opensFloatingUi: true,
                    disabledReason: chatDisabledReason,
                    onSelect: () => {
                        captureScoutCreatePathChosen({ path: 'chat', surface: 'fleet_list' })
                        setChatOpen(true)
                    },
                },
                {
                    id: 'scout-new-form',
                    label: 'Fill in the form',
                    icon: <IconDocument />,
                    opensFloatingUi: true,
                    onSelect: () => {
                        captureScoutCreatePathChosen({ path: 'form', surface: 'fleet_list' })
                        setScoutTemplateDraft({})
                    },
                },
            ],
            pinned: {
                order: 1,
                variant: 'primary',
                dataAttr: 'scout-new',
                render: () => <ScoutNewButton surface="fleet_list" size="small" onCreated={() => loadScoutConfigs()} />,
            },
        },
        ...(suggestButtonVisible
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      id: `${RESOURCE_TYPE}-menubar-suggest-scout`,
                      label: 'Suggest a scout',
                      icon: <IconSparkles />,
                      disabledReason: suggestDisabledReason,
                      onSelect: () => askForSuggestions(),
                      pinned: { order: 3, variant: 'secondary', dataAttr: 'scout-suggestions-show' },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'file',
            section: 'ask',
            type: 'submenu',
            id: `${RESOURCE_TYPE}-menubar-ask`,
            label: 'Ask',
            icon: <IconSparkles />,
            items: ASK_PROMPTS.map(({ label, chatType }) => ({
                id: `${RESOURCE_TYPE}-menubar-ask-${chatType}`,
                label,
                disabledReason: askDisabledReason,
                onSelect: () => startScoutChatTask(chatType, label),
            })),
            pinned: { order: 2, variant: 'secondary' },
        },
        ...(currentTeamId === 2 && user?.is_staff
            ? ([
                  {
                      group: 'staff',
                      id: `${RESOURCE_TYPE}-menubar-scout-trials`,
                      dataAttr: 'scout-open-comparisons',
                      label: 'Trials',
                      disabledReason: creationDisabledReason,
                      onSelect: () => router.actions.push(urls.inboxScoutTrials()),
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return (
        <>
            <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
            {chatOpen ? (
                <ScoutChatModal
                    onClose={() => setChatOpen(false)}
                    onSwitchToForm={(prompt) => {
                        setChatOpen(false)
                        setScoutTemplateDraft(prompt ? { description: prompt } : {})
                    }}
                />
            ) : null}
        </>
    )
}
