import { useValues } from 'kea'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DEFAULT_SKILLS_TAB_KEY, skillTabUrl, skillTabsLogic, visibleCategoryTabs } from './skillTabsLogic'

/** Tab key for the Community scene, and its `/skills/<key>` URL segment. */
export const COMMUNITY_SKILLS_TAB_KEY = 'community'

export const COMMUNITY_SKILLS_TAB_DESCRIPTION = 'Discover and install agent skills shared by the PostHog community.'

/**
 * Shared shell for every Skills tab. It renders one tab bar — the default "Skills" tab, the
 * category tabs (Scouts, Code review), then "Community" — so the category tabs and Community sit
 * in the same row instead of stacking two bars.
 *
 * Community is a separate scene (at /skills/community), so each scene renders this with only its own
 * tab's content; the other tabs navigate via their `link` and are never mounted here. That keeps the
 * two scenes' logics independent while presenting them as one tabbed surface. The Community tab is
 * gated behind the community-skills flag (but stays visible when it's already the active tab, so a
 * direct URL still renders cleanly).
 */
export function SkillsSceneShell({
    activeTabKey,
    actions,
    description,
    content,
}: {
    activeTabKey: string
    actions?: JSX.Element
    description: string
    content: JSX.Element
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    // Mounted on the Community scene too, so switching to Community doesn't drop the category tabs
    // out of the row. It only probes the per-category counts, not the skills list.
    const { categoryCounts } = useValues(skillTabsLogic)
    const communityEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_COMMUNITY_SKILLS]

    const tabs: LemonTab<string>[] = [
        { key: DEFAULT_SKILLS_TAB_KEY, label: 'Skills', link: skillTabUrl(DEFAULT_SKILLS_TAB_KEY) },
        ...visibleCategoryTabs(categoryCounts, activeTabKey).map((tab) => ({
            key: tab.key,
            label: tab.label,
            link: skillTabUrl(tab.key),
        })),
        ...(communityEnabled || activeTabKey === COMMUNITY_SKILLS_TAB_KEY
            ? [{ key: COMMUNITY_SKILLS_TAB_KEY, label: 'Community', link: urls.communitySkills() }]
            : []),
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Skills"
                description={description}
                resourceType={{ type: 'llm_analytics' }}
                actions={actions}
            />
            {/* The bar carries no tab content, so `content` keeps its place in the tree when the
                category counts land and the bar appears. Only surface the bar once there's
                somewhere else to go — otherwise the lone "Skills" tab is noise. */}
            {tabs.length > 1 && <LemonTabs activeKey={activeTabKey} data-attr="skills-tabs" tabs={tabs} sceneInset />}
            {content}
        </SceneContent>
    )
}
