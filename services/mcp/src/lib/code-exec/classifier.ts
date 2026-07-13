/**
 * Mutation classifier. The proxy sees raw HTTP, and "mutation" is not
 * `method !== 'GET'` — `POST /api/.../query/` is a read. A generated table
 * (shape mirrored by `ClassifierTable`) drives the decision; matching is by
 * template segment with `{param}` wildcards, tolerant of trailing slashes and
 * query strings, and treats `/api/projects/` and `/api/environments/` as
 * interchangeable prefixes. Unmatched GET/HEAD is a read; anything else
 * unmatched is a mutation with `operationId: null` — fail closed.
 */

import type { Classification, ClassifierOperation, ClassifierTable } from './types'

export interface Classifier {
    classify(method: string, path: string, body?: unknown): Classification
}

interface CompiledOperation {
    operation: ClassifierOperation
    method: string
    /** Canonical template segments (environments prefix folded to projects). */
    segments: string[]
}

export function createClassifier(table: ClassifierTable): Classifier {
    const compiled: CompiledOperation[] = []
    for (const operation of table.operations) {
        const method = operation.method.toUpperCase()
        for (const template of [operation.pathTemplate, ...operation.pathAliases]) {
            compiled.push({ operation, method, segments: toSegments(canonicalizePrefix(template)) })
        }
    }

    return {
        classify(method, path): Classification {
            const upperMethod = method.toUpperCase()
            const requestSegments = toSegments(canonicalizePrefix(stripToPath(path)))
            for (const candidate of compiled) {
                if (candidate.method === upperMethod && segmentsMatch(candidate.segments, requestSegments)) {
                    return {
                        kind: candidate.operation.readOnly ? 'read' : 'mutation',
                        operationId: candidate.operation.id,
                        operation: candidate.operation,
                    }
                }
            }
            const kind = upperMethod === 'GET' || upperMethod === 'HEAD' ? 'read' : 'mutation'
            return { kind, operationId: null, operation: null }
        },
    }
}

/** Strip an origin and any query string, leaving just the pathname. */
function stripToPath(path: string): string {
    const withoutQuery = path.split('?')[0] ?? path
    if (withoutQuery.includes('://')) {
        try {
            return new URL(withoutQuery).pathname
        } catch {
            return withoutQuery
        }
    }
    return withoutQuery
}

/** Fold the `/api/environments/` alias onto `/api/projects/` for matching. */
function canonicalizePrefix(path: string): string {
    return path.replace('/api/environments/', '/api/projects/')
}

/** Split into non-empty segments, so a trailing slash is tolerated. */
function toSegments(path: string): string[] {
    return path.split('/').filter((segment) => segment.length > 0)
}

function segmentsMatch(template: string[], request: string[]): boolean {
    if (template.length !== request.length) {
        return false
    }
    for (let i = 0; i < template.length; i++) {
        const templateSegment = template[i]!
        const isWildcard = templateSegment.startsWith('{') && templateSegment.endsWith('}')
        if (!isWildcard && templateSegment !== request[i]) {
            return false
        }
    }
    return true
}
