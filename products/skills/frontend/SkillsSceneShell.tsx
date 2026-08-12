import { useValues } from 'kea'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
 * presenting them as one tabbed surface. The Community tab is gated behind the community-skills
 * flag (but stays visible when it's already the active tab, so a direct URL still renders cleanly).
 */
export function SkillsSceneShell({
    activeTab,
    actions,
    description,
    content,
}: {
    activeTab: SkillsTab
    actions?: JSX.Element
    description?: string
    content: JSX.Element
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const communityEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_COMMUNITY_SKILLS]

    const tabs: LemonTab<SkillsTab>[] = [
        {
            key: 'your',
            label: 'Your skills',
            link: urls.skills(),
            content: activeTab === 'your' ? content : <></>,
        },
        ...(communityEnabled || activeTab === 'community'
            ? [
                  {
                      key: 'community' as SkillsTab,
                      label: 'Community',
                      link: urls.communitySkills(),
                      content: activeTab === 'community' ? content : <></>,
                  },
              ]
            : []),
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Skills"
                description={description ?? TAB_DESCRIPTIONS[activeTab]}
                resourceType={{ type: 'llm_analytics' }}
                actions={actions}
            />
            {/* Only surface the tab bar once Community is reachable — otherwise the lone "Your skills"
                tab is noise, so flag-off users see the plain Skills scene exactly as before. */}
            {tabs.length > 1 ? (
                <LemonTabs activeKey={activeTab} data-attr="skills-tabs" tabs={tabs} sceneInset />
            ) : (
                content
            )}
        </SceneContent>
    )
}
