import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export type SkillsTab = 'your' | 'community'

const TAB_DESCRIPTIONS: Record<SkillsTab, string> = {
    your: 'Manage versioned agent skills that any MCP-connected agent can discover and use.',
    community: 'Discover and install agent skills shared by the PostHog community.',
}

/**
 * Shared shell for the two Skills tabs ("Your skills" and "Community"). Each scene renders this
 * with only its own tab's content; the inactive tab navigates via its `link`, so its content is
 * never mounted here. This keeps the two scenes' logics (and URL contracts) independent while
 * presenting them as one tabbed surface.
 */
export function SkillsSceneShell({
    activeTab,
    actions,
    content,
}: {
    activeTab: SkillsTab
    actions?: JSX.Element
    content: JSX.Element
}): JSX.Element {
    const tabs: LemonTab<SkillsTab>[] = [
        {
            key: 'your',
            label: 'Your skills',
            link: urls.skills(),
            content: activeTab === 'your' ? content : <></>,
        },
        {
            key: 'community',
            label: 'Community',
            link: urls.communitySkills(),
            content: activeTab === 'community' ? content : <></>,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Skills"
                description={TAB_DESCRIPTIONS[activeTab]}
                resourceType={{ type: 'llm_analytics' }}
                actions={actions}
            />
            <LemonTabs activeKey={activeTab} data-attr="skills-tabs" tabs={tabs} sceneInset />
        </SceneContent>
    )
}
