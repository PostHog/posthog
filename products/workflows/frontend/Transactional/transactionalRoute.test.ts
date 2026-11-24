import { TransactionalRoute, transactionalRouteFor } from './transactionalRoute'

describe('transactionalRouteFor', () => {
    test.each<[string, TransactionalRoute | null]>([
        ['/transactional', 'transactional'],
        ['/project/2/transactional', 'transactional'],
        ['/project/2/transactional/log', 'log'],
        ['/project/2/transactional/metrics', 'metrics'],
        ['/project/2/transactional/library', 'library'],
        ['/project/2/transactional/new', 'new'],
        ['/project/2/transactional/webhooks', 'webhooks'],
        ['/project/2/transactional/log/01a1acb5-7506-0001-0f02-b0f2c0c0c108', null],
        ['/project/2/transactional/library/templates/01a167d1-baf4-0000-256f-bb8a70449dd5', null],
        ['/project/2/insights/abc123', null],
    ])('%s', (pathname, expected) => {
        expect(transactionalRouteFor(pathname)).toBe(expected)
    })
})
