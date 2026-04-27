import { z } from 'zod'

import type { Searcher, SearchOutput } from '../lib/searcher'

export const SearchInputSchema = {
    query: z.string().optional().describe('Natural-language query. Empty/missing returns the full index, paginated.'),
    kind: z
        .enum(['operation', 'type', 'all'])
        .optional()
        .describe('Restrict to operations, types, or both. Defaults to "all".'),
    page: z.number().int().min(1).optional().describe('1-indexed page number. Default 1.'),
    pageSize: z.number().int().min(1).max(100).optional().describe('Hits per page. Default 25, capped at 100.'),
}

export class SearchTool {
    constructor(private searcher: Searcher) {}

    handle(args: {
        query?: string
        kind?: 'operation' | 'type' | 'all'
        page?: number
        pageSize?: number
    }): SearchOutput {
        return this.searcher.search(args)
    }
}
