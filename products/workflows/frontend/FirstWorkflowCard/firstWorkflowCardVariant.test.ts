import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import type { ProductIntentType } from '~/types'

import { firstWorkflowCardVariant } from './firstWorkflowCardVariant'

const workflowsIntent = { product_type: ProductKey.WORKFLOWS } as ProductIntentType
const replayIntent = { product_type: ProductKey.SESSION_REPLAY } as ProductIntentType

function flagsRecordingReads(variant: string): { featureFlags: FeatureFlagsSet; readFlags: string[] } {
    const readFlags: string[] = []
    const featureFlags = new Proxy({} as FeatureFlagsSet, {
        get(_, flag) {
            readFlags.push(String(flag))
            return flag === FEATURE_FLAGS.WORKFLOWS_FIRST_WORKFLOW_CARD ? variant : undefined
        },
    })
    return { featureFlags, readFlags }
}

describe('firstWorkflowCardVariant', () => {
    it.each([
        ['a project that never created a workflow', [replayIntent], 'test', 'test'],
        ['a project that never created a workflow, in control', [], 'control', 'control'],
    ])('returns the experiment variant for %s', (_label, productIntents, variant, expected) => {
        const { featureFlags } = flagsRecordingReads(variant)

        expect(firstWorkflowCardVariant({ product_intents: productIntents }, featureFlags)).toBe(expected)
    })

    // Reading the flag records an experiment exposure, so a project outside the audience must
    // never read it, or the experiment counts people who could never see the card.
    it.each([
        ['a project that already uses Workflows', { product_intents: [workflowsIntent] }],
        ['a project whose intents have not loaded', { product_intents: undefined }],
        ['no current project', null],
    ])('returns null without reading the flag for %s', (_label, team) => {
        const { featureFlags, readFlags } = flagsRecordingReads('test')

        expect(firstWorkflowCardVariant(team, featureFlags)).toBeNull()
        expect(readFlags).toEqual([])
    })
})
