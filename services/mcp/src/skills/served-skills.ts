import z from 'zod'

import servedSkillsJson from '@/generated/served-skills.json'
import { POSTHOG_AI_CONSUMER, SLACK_CONSUMER } from '@/lib/client-detection'
import type { EvaluatedFlags } from '@/lib/posthog/flags'

import type { SkillHeader } from './skill-catalog'

// The PostHog-run agents that read skills through `learn`. Other PostHog consumers read an installed copy.
const SkillConsumerSchema = z.enum([SLACK_CONSUMER, POSTHOG_AI_CONSUMER])

const ServedSkillSchema = z.strictObject({
    // The generated file carries each product skill's audience. A skill with any other audience must not be in it.
    audience: z.enum(['customer', 'scout']).optional(),
    feature_flag: z.string().min(1).optional(),
    consumers: z.array(SkillConsumerSchema).min(1).optional(),
})

// Strict, so a misspelled key fails the load instead of serving a gated skill to everyone.
const ServedSkillsSchema = z.strictObject({
    skills: z.record(z.string(), ServedSkillSchema),
})

export type ServedSkills = ReadonlyMap<string, z.infer<typeof ServedSkillSchema>>

export interface SkillCaller {
    featureFlags?: EvaluatedFlags | undefined
    consumer?: string | undefined
}

export function parseServedSkills(json: unknown): ServedSkills {
    return new Map(Object.entries(ServedSkillsSchema.parse(json).skills))
}

// The product skills, from the file generated from their headers.
export const PRODUCT_SERVED_SKILLS = parseServedSkills(servedSkillsJson)

// Context-mill skills live in another repo, so no generated file lists them. Each one says in its
// own header who it is for, and a skill whose header does not say `customer` is not served.
export function servedSkillsFromHeaders(headers: Iterable<SkillHeader>): ServedSkills {
    const served = new Map<string, z.infer<typeof ServedSkillSchema>>()
    for (const { name, audience, featureFlag } of headers) {
        if (audience === 'customer') {
            served.set(name, { audience, ...(featureFlag ? { feature_flag: featureFlag } : {}) })
        }
    }
    return served
}

export function getServedSkillFeatureFlags(served: ServedSkills = PRODUCT_SERVED_SKILLS): string[] {
    return [...new Set([...served.values()].flatMap(({ feature_flag }) => (feature_flag ? [feature_flag] : [])))]
}

export function isSkillListed(name: string, served: ServedSkills = PRODUCT_SERVED_SKILLS): boolean {
    return served.has(name)
}

// For a caller that cannot evaluate feature flags, such as the CLI. It leaves out a skill limited to one consumer.
export function isSkillServedWithoutFlags(name: string, served: ServedSkills = PRODUCT_SERVED_SKILLS): boolean {
    const entry = served.get(name)
    return entry !== undefined && entry.consumers === undefined
}

export function isSkillServed(
    name: string,
    caller: SkillCaller = {},
    served: ServedSkills = PRODUCT_SERVED_SKILLS
): boolean {
    const entry = served.get(name)
    if (!entry) {
        return false
    }
    if (entry.feature_flag !== undefined && caller.featureFlags?.[entry.feature_flag] !== true) {
        return false
    }
    return entry.consumers === undefined || entry.consumers.some((consumer) => consumer === caller.consumer)
}
