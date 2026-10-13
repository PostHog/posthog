import { useValues } from 'kea'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

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
 * two scenes' logics independent while presenting them as one tabbed surface.
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
    // Mounted on the Community scene too, so switching to Community doesn't drop the category tabs
    // out of the row. It only probes the per-category counts, not the skills list.
    const { categoryCounts } = useValues(skillTabsLogic)

    const tabs: LemonTab<string>[] = [
        { key: DEFAULT_SKILLS_TAB_KEY, label: 'Skills', link: skillTabUrl(DEFAULT_SKILLS_TAB_KEY) },
        ...visibleCategoryTabs(categoryCounts, activeTabKey).map((tab) => ({
            key: tab.key,
            label: tab.label,
            link: skillTabUrl(tab.key),
        })),
        { key: COMMUNITY_SKILLS_TAB_KEY, label: 'Community', link: urls.communitySkills() },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Skills"
                description={description}
                resourceType={{ type: 'llm_analytics' }}
                actions={actions}
            />
            <LemonTabs activeKey={activeTabKey} data-attr="skills-tabs" tabs={tabs} sceneInset />
            {content}
        </SceneContent>
    )
}
