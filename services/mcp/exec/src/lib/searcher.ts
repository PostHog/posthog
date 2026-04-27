import Fuse from 'fuse.js'

export interface SearchDoc {
    id: string
    kind: 'operation' | 'type'
    name: string
    description: string
    summary: string
    snippet: string
}

export interface SearchHit {
    kind: 'operation' | 'type'
    name: string
    snippet: string
    score: number
}

export interface SearchOptions {
    query?: string
    kind?: 'operation' | 'type' | 'all'
    page?: number
    pageSize?: number
}

export interface SearchOutput {
    hits: SearchHit[]
    page: number
    pageSize: number
    total: number
}

const PAGE_SIZE_CAP = 100

export class Searcher {
    private readonly fuse: Fuse<SearchDoc>
    private readonly docs: SearchDoc[]

    constructor(docs: SearchDoc[]) {
        this.docs = docs
        this.fuse = new Fuse(docs, {
            keys: [
                { name: 'description', weight: 3 },
                { name: 'summary', weight: 2 },
                { name: 'name', weight: 1 },
            ],
            includeScore: true,
            threshold: 0.4,
            ignoreLocation: true,
            minMatchCharLength: 2,
        })
    }

    search(options: SearchOptions): SearchOutput {
        const page = Math.max(1, options.page ?? 1)
        const pageSize = Math.min(PAGE_SIZE_CAP, Math.max(1, options.pageSize ?? 25))
        const kindFilter = options.kind ?? 'all'

        const hits = this.runQuery(options.query, kindFilter)
        const total = hits.length
        const start = (page - 1) * pageSize
        const slice = hits.slice(start, start + pageSize)

        return {
            hits: slice,
            page,
            pageSize,
            total,
        }
    }

    private runQuery(query: string | undefined, kindFilter: 'operation' | 'type' | 'all'): SearchHit[] {
        if (!query || query.trim() === '') {
            return this.docs
                .filter((doc) => kindFilter === 'all' || doc.kind === kindFilter)
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((doc) => ({ kind: doc.kind, name: doc.name, snippet: doc.snippet, score: 0 }))
        }

        const results = this.fuse.search(query)
        const hits: SearchHit[] = []
        for (const r of results) {
            if (kindFilter !== 'all' && r.item.kind !== kindFilter) {
                continue
            }
            hits.push({
                kind: r.item.kind,
                name: r.item.name,
                snippet: r.item.snippet,
                // Fuse score is 0 (perfect) → 1 (worst). Invert to a "higher-is-better" score.
                score: 1 - (r.score ?? 0),
            })
        }
        return hits
    }
}
