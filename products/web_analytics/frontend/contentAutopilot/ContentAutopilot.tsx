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
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'
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
    const { workspaceTab } = useValues(contentAutopilotLogic)
    const { onboarding, setupContext, setupContextError, setupContextLoading } = useValues(contentAutopilotSetupLogic)
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const { loadSetupContext } = useActions(contentAutopilotSetupLogic)

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
        {
            key: 'settings',
            label: 'Settings',
            // pinned: was the settings gear's data-attr
            'data-attr': 'content-autopilot-settings',
            content: (
                <div className="flex flex-col gap-4" data-attr="content-autopilot-settings-page">
                    <ContentAutopilotSettings />
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4 pb-4" data-quill>
            {promptId ? (
                <ContentAutopilotPromptDetail />
            ) : setupContextError && !setupContext ? (
                // Without the context neither the setup wizard nor the overview can tell what to show.
                <div data-attr="content-autopilot-setup-context-error">
                    <AiVisibilityBanner
                        type="error"
                        action={{ children: 'Try again', onClick: loadSetupContext, loading: setupContextLoading }}
                    >
                        Couldn't load AI visibility. Try again, and if it keeps happening contact support.
                    </AiVisibilityBanner>
                </div>
            ) : onboarding && workspaceTab === 'overview' ? (
                // Setup runs as a wizard in place of the tabs, until the first results are in.
                <ContentAutopilotPromptsOverview />
            ) : (
                <ContentAutopilotWorkspaceTabs tabs={tabs} activeKey={workspaceTab} onChange={setWorkspaceTab} />
            )}
            <ContentAutopilotPromptAddModal />
            <ContentAutopilotPromptSuggestModal />
            <ContentAutopilotCitationsModal />
        </div>
    )
}
