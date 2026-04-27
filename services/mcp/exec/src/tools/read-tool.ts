import { z } from 'zod'

import type { ReadResult, TypeReader } from '../lib/type-reader'

export const ReadInputSchema = {
    kind: z.enum(['operation', 'type']).describe('Whether to read a Client method or a Schemas type.'),
    name: z.string().min(1).describe('camelCase methodName for kind=operation, PascalCase type name for kind=type.'),
}

export interface ReadOutput {
    kind: 'operation' | 'type'
    name: string
    source: string
    found: boolean
}

export class ReadTool {
    constructor(private reader: TypeReader) {}

    handle(args: { kind: 'operation' | 'type'; name: string }): ReadOutput {
        const result: ReadResult | null = this.reader.read(args.kind, args.name)
        if (!result) {
            return {
                kind: args.kind,
                name: args.name,
                source: `// not found: ${args.kind} '${args.name}'. Use the search tool to find available names.`,
                found: false,
            }
        }
        return { ...result, found: true }
    }
}
