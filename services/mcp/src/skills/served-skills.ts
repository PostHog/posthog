import z from 'zod'

import type { EvaluatedFlags } from '@/lib/posthog/flags'

import servedSkillsJson from './served-skills.json'

const ServedSkillSchema = z.strictObject({
    feature_flag: z.string().min(1).optional(),
})

// Strict, so a misspelled key fails the load instead of serving a gated skill to everyone.
const ServedSkillsSchema = z.strictObject({
    skills: z.record(z.string(), ServedSkillSchema),
    context_mill_skills: z.record(z.string(), ServedSkillSchema),
})

export type ServedSkills = Map<string, z.infer<typeof ServedSkillSchema>>

export function parseServedSkills(json: unknown): ServedSkills {
    const { skills, context_mill_skills } = ServedSkillsSchema.parse(json)
    return new Map([...Object.entries(skills), ...Object.entries(context_mill_skills)])
}

const SERVED_SKILLS = parseServedSkills(servedSkillsJson)

export function getServedSkillFeatureFlags(served: ServedSkills = SERVED_SKILLS): string[] {
    return [...new Set([...served.values()].flatMap(({ feature_flag }) => (feature_flag ? [feature_flag] : [])))]
}

/** A flag gates a skill by the same rule as a tool's `feature_flag`: the value must be `true`. */
export function isSkillServed(
    name: string,
    featureFlags: EvaluatedFlags = {},
    served: ServedSkills = SERVED_SKILLS
): boolean {
    const entry = served.get(name)
    if (!entry) {
        return false
    }
    return entry.feature_flag === undefined || featureFlags[entry.feature_flag] === true
}
