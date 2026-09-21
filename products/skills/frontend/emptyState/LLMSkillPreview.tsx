import './LLMSkillPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

interface PreviewSkill {
    id: string
    name: string
    description: string
    version: string
    instructions: string
}

// Example skills - hand-authored, not real data. `id` keys the radio that drives
// the `:checked ~` selection styles.
const SKILLS: PreviewSkill[] = [
    {
        id: 'deploy',
        name: 'deploying-frontend',
        description: 'Deploy checklist for the web app',
        version: 'v4',
        instructions: '12 instructions applied',
    },
    {
        id: 'migrate',
        name: 'writing-migrations',
        description: 'Zero-downtime schema changes',
        version: 'v2',
        instructions: '8 instructions applied',
    },
    {
        id: 'review',
        name: 'reviewing-prs',
        description: 'House style for code review',
        version: 'v7',
        instructions: '15 instructions applied',
    },
]

/**
 * Example-data preview for the skills empty state: the published skill library
 * wired to a mini coding-agent terminal, so picking a skill shows the agent loading
 * it with `/posthog-skill-store:<name>` and applying its instructions. The whole
 * interaction is three hidden radios driving `:checked ~` styles - no timers or
 * state, per the preview rules in the `building-product-empty-states` skill.
 * Per-skill terminal lines are stacked in `__swap` grids and crossfaded, so
 * switching skills never changes the layout's size.
 */
export function LLMSkillPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('SkillPreview', isStatic && 'SkillPreview--static')}>
            {/* Selected-skill state, before both cards so `:checked ~` can style them. */}
            {SKILLS.map((skill, i) => (
                <input
                    key={skill.id}
                    type="radio"
                    name="skill-preview-skill"
                    id={`skill-preview-${skill.id}`}
                    defaultChecked={i === 0}
                    className="SkillPreview__radio"
                />
            ))}

            <div className="SkillPreview__list">
                <div className="SkillPreview__head">
                    <span className="SkillPreview__title">Skills</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="SkillPreview__rows">
                    {SKILLS.map((skill) => (
                        <label
                            key={skill.id}
                            htmlFor={`skill-preview-${skill.id}`}
                            className={`SkillPreview__row SkillPreview__row--${skill.id}`}
                        >
                            <span
                                className={`SkillPreview__vradio SkillPreview__vradio--${skill.id}`}
                                aria-hidden="true"
                            />
                            <span className="SkillPreview__copy">
                                <span className="SkillPreview__name">{skill.name}</span>
                                <span className="SkillPreview__desc">{skill.description}</span>
                            </span>
                            <span className="SkillPreview__version">{skill.version}</span>
                        </label>
                    ))}
                </div>

                <div className="SkillPreview__hint">Select a skill to load it in the agent below.</div>
            </div>

            <div className="SkillPreview__terminal">
                <div className="SkillPreview__chrome">
                    <span className="SkillPreview__chrome-dot" />
                    <span className="SkillPreview__chrome-dot" />
                    <span className="SkillPreview__chrome-dot" />
                    <span className="SkillPreview__chrome-title">Claude Code</span>
                </div>
                <div className="SkillPreview__screen">
                    <div className="SkillPreview__line SkillPreview__swap">
                        {SKILLS.map((skill) => (
                            <span key={skill.id} className={`SkillPreview__when-${skill.id}`}>
                                <span className="SkillPreview__prompt-char">&gt;</span>{' '}
                                <span className="SkillPreview__cmd">/posthog-skill-store:{skill.name}</span>
                            </span>
                        ))}
                    </div>
                    <div className="SkillPreview__line SkillPreview__swap">
                        {SKILLS.map((skill) => (
                            <span key={skill.id} className={`SkillPreview__when-${skill.id}`}>
                                <span className="SkillPreview__ok">✓</span> Loaded {skill.version} ·{' '}
                                {skill.instructions}
                            </span>
                        ))}
                    </div>
                    <div className="SkillPreview__line SkillPreview__swap">
                        {SKILLS.map((skill) => (
                            <span key={skill.id} className={`SkillPreview__muted SkillPreview__when-${skill.id}`}>
                                Following {skill.name} for this task…
                            </span>
                        ))}
                    </div>
                    <div className="SkillPreview__line">
                        <span className="SkillPreview__cursor" aria-hidden="true" />
                    </div>
                </div>
            </div>
        </div>
    )
}
