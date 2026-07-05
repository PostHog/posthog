import { describe, expect, it } from 'vitest'

import { createClassifier } from '@/lib/code-exec'

import { FIXTURE_TABLE } from './fixtures'

const classifier = createClassifier(FIXTURE_TABLE)

describe('classifier', () => {
    it.each([
        {
            name: 'query POST resolves to a read (the fail-closed collision)',
            method: 'POST',
            path: '/api/environments/2/query/',
            kind: 'read',
            operationId: 'query.run',
        },
        {
            name: 'query POST via the projects alias also reads',
            method: 'POST',
            path: '/api/projects/2/query/',
            kind: 'read',
            operationId: 'query.run',
        },
        {
            name: 'create POST is a mutation',
            method: 'POST',
            path: '/api/projects/2/feature_flags/',
            kind: 'mutation',
            operationId: 'featureFlags.create',
        },
        {
            name: 'environments alias matches a projects template',
            method: 'PATCH',
            path: '/api/environments/2/feature_flags/5/',
            kind: 'mutation',
            operationId: 'featureFlags.update',
        },
        {
            name: 'trailing slash and query string are tolerated',
            method: 'GET',
            path: '/api/projects/2/feature_flags/5?include=filters',
            kind: 'read',
            operationId: 'featureFlags.get',
        },
        {
            name: 'unmatched GET falls back to a read',
            method: 'GET',
            path: '/api/projects/2/unknown/',
            kind: 'read',
            operationId: null,
        },
        {
            name: 'unmatched POST fails closed to a mutation',
            method: 'POST',
            path: '/api/projects/2/unknown/',
            kind: 'mutation',
            operationId: null,
        },
    ])('classifies $name', ({ method, path, kind, operationId }) => {
        const result = classifier.classify(method, path)
        expect(result.kind).toBe(kind)
        expect(result.operationId).toBe(operationId)
    })
})
