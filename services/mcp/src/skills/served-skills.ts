import z from 'zod'

import { POSTHOG_AI_CONSUMER, SLACK_CONSUMER } from '@/lib/client-detection'
import type { EvaluatedFlags } from '@/lib/posthog/flags'

import servedSkillsJson from './served-skills.json'

// The PostHog-run agents that read skills through `learn`. Other PostHog consumers read an installed copy.
const SkillConsumerSchema = z.enum([SLACK_CONSUMER, POSTHOG_AI_CONSUMER])

const ServedSkillSchema = z.strictObject({
    feature_flag: z.string().min(1).optional(),
    consumers: z.array(SkillConsumerSchema).min(1).optional(),
})

// Strict, so a misspelled key fails the load instead of serving a gated skill to everyone.
const ServedSkillsSchema = z.strictObject({
    skills: z.record(z.string(), ServedSkillSchema),
    context_mill_skills: z.record(z.string(), ServedSkillSchema),
})

export type ServedSkills = Map<string, z.infer<typeof ServedSkillSchema>>

export interface SkillCaller {
    featureFlags?: EvaluatedFlags | undefined
    consumer?: string | undefined
}

export function parseServedSkills(json: unknown): ServedSkills {
    const { skills, context_mill_skills } = ServedSkillsSchema.parse(json)
    return new Map([...Object.entries(skills), ...Object.entries(context_mill_skills)])
}

const SERVED_SKILLS = parseServedSkills(servedSkillsJson)

export function getServedSkillFeatureFlags(served: ServedSkills = SERVED_SKILLS): string[] {
    return [...new Set([...served.values()].flatMap(({ feature_flag }) => (feature_flag ? [feature_flag] : [])))]
}

export function isSkillListed(name: string, served: ServedSkills = SERVED_SKILLS): boolean {
    return served.has(name)
}

export function isSkillServed(name: string, caller: SkillCaller = {}, served: ServedSkills = SERVED_SKILLS): boolean {
    const entry = served.get(name)
    if (!entry) {
        return false
    }
    if (entry.feature_flag !== undefined && caller.featureFlags?.[entry.feature_flag] !== true) {
        return false
    }
    return entry.consumers === undefined || entry.consumers.some((consumer) => consumer === caller.consumer)
}
