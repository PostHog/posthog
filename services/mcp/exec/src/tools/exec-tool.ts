import { z } from 'zod'

import type { ExecResult, SnippetRunner } from '../lib/runner'

export const ExecInputSchema = {
    snippet: z
        .string()
        .min(1)
        .describe(
            'TypeScript snippet body. Has access to a `client` binding (see sdk.d.ts → Client interface) and `console`. Can use `await`. Should `return` a value.'
        ),
    timeoutMs: z.number().int().min(100).max(120_000).optional().describe('Timeout in milliseconds. Default 15000.'),
    maxBytes: z
        .number()
        .int()
        .min(256)
        .max(65_536)
        .optional()
        .describe(
            'Max bytes for the serialized return value. Default 8192. Larger values are truncated with a shape hint.'
        ),
}

export class ExecTool {
    constructor(private runner: SnippetRunner) {}

    async handle(args: { snippet: string; timeoutMs?: number; maxBytes?: number }): Promise<ExecResult> {
        return this.runner.run(args)
    }
}
