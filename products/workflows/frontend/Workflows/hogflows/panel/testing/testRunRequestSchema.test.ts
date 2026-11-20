import { HogFlowsInvocationsCreateBody } from 'products/workflows/frontend/generated/api.zod'

describe('test run request schema', () => {
    it('never asks a configuration override for the response-only warnings', () => {
        const result = HogFlowsInvocationsCreateBody.safeParse({ configuration: {} })

        const paths = result.success ? [] : result.error.issues.map((issue) => issue.path.join('.'))
        expect(paths).not.toContain('configuration.warnings')
    })
})
