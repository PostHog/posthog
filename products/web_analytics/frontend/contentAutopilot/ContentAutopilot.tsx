import { useActions, useValues } from 'kea'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AI_VISIBILITY_TAB_FILTERS, type AiVisibilityFilterTab } from './aiVisibilityFilters'
import { ContentAutopilotCitationsModal } from './ContentAutopilotCitationsModal'
import { ContentAutopilotFilterBar } from './ContentAutopilotFilterBar'
import { ContentAutopilotKeywords } from './ContentAutopilotKeywords'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPromptAddModal } from './ContentAutopilotPromptAddModal'
import { ContentAutopilotPromptDetail } from './ContentAutopilotPromptDetail'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPrompts } from './ContentAutopilotPrompts'
import { ContentAutopilotPromptsOverview } from './ContentAutopilotPromptsOverview'
import { ContentAutopilotPromptSuggestModal } from './ContentAutopilotPromptSuggestModal'
import { ContentAutopilotRankings } from './ContentAutopilotRankings'
import { ContentAutopilotSettings } from './ContentAutopilotSettings'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'
import { ContentAutopilotSitePicker } from './ContentAutopilotSitePicker'
import {
    type ContentAutopilotWorkspaceTabDefinition,
    ContentAutopilotWorkspaceTabs,
} from './ContentAutopilotWorkspaceTabs'

const FilteredTab = ({
    tab,
    children,
}: {
    tab: Exclude<AiVisibilityFilterTab, 'prompts'>
    children: JSX.Element
}): JSX.Element => (
    <div className="flex flex-col gap-4">
        <ContentAutopilotFilterBar tab={tab} filters={AI_VISIBILITY_TAB_FILTERS[tab]} />
        {children}
    </div>
)

export const ContentAutopilot = (): JSX.Element => {
    // Mounted here, so a prompt's own URL opens it whatever tab was last open.
    const { promptId } = useValues(contentAutopilotPromptDetailLogic)
    const { profile, workspaceTab, onboardingOpen, siteProfilesLoading, workspaceError } =
        useValues(contentAutopilotLogic)
    const { loadWorkspace, setWorkspaceTab } = useActions(contentAutopilotLogic)

    const tabs: ContentAutopilotWorkspaceTabDefinition[] = [
        {
            key: 'overview',
            label: 'Overview',
            content: (
                <FilteredTab tab="overview">
                    <ContentAutopilotPromptsOverview />
                </FilteredTab>
            ),
        },
        {
            key: 'rankings',
            label: 'Rankings',
            content: (
                <FilteredTab tab="rankings">
                    <ContentAutopilotRankings />
                </FilteredTab>
            ),
        },
        {
            key: 'prompts',
            label: 'Prompts',
            content: <ContentAutopilotPrompts />,
        },
        {
            key: 'keywords',
            label: 'Keywords',
            content: (
                <FilteredTab tab="keywords">
                    <ContentAutopilotKeywords />
                </FilteredTab>
            ),
        },
        // Settings belong to a site, so the tab waits until one is set up.
        ...(profile
            ? [
                  {
                      key: 'settings' as const,
                      label: 'Settings',
                      // pinned: was the settings gear's data-attr
                      'data-attr': 'content-autopilot-settings',
                      content: (
                          <div className="flex flex-col gap-4" data-attr="content-autopilot-settings-page">
                              <ContentAutopilotSitePicker />
                              <ContentAutopilotSettings />
                          </div>
                      ),
                  },
              ]
            : []),
    ]

    return (
        <div className="flex flex-col gap-4 pb-4" data-quill>
            {workspaceError ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadWorkspace, loading: siteProfilesLoading }}
                >
                    Some AI visibility data could not be loaded. {workspaceError}
                </AiVisibilityBanner>
            ) : null}

            {profile && onboardingOpen ? (
                <ContentAutopilotSetup onboarding />
            ) : promptId ? (
                <ContentAutopilotPromptDetail />
            ) : (
                <ContentAutopilotWorkspaceTabs
                    tabs={tabs}
                    activeKey={workspaceTab === 'settings' && !profile ? 'overview' : workspaceTab}
                    onChange={setWorkspaceTab}
                />
            )}
            <ContentAutopilotPromptAddModal />
            <ContentAutopilotPromptSuggestModal />
            <ContentAutopilotCitationsModal />
        </div>
    )
}
