import { initKeaTests } from '~/test/init'

import { getNotebookWidgetTrust, type NotebookWidgetTrust, notebookWidgetTrustLogic } from './notebookWidgetTrustLogic'

const BUILD_HASH = 'a'.repeat(64)

describe('notebookWidgetTrustLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        notebookWidgetTrustLogic.mount()
    })

    afterEach(() => {
        notebookWidgetTrustLogic.unmount()
    })

    function trustFor({
        userId = 12,
        buildHash = BUILD_HASH,
    }: {
        userId?: number | null
        buildHash?: string | null
    } = {}): NotebookWidgetTrust {
        return getNotebookWidgetTrust({
            trustByUser: notebookWidgetTrustLogic.values.trustByUser,
            sessionBuildHashes: notebookWidgetTrustLogic.values.sessionBuildHashes,
            userId,
            buildHash,
        })
    }

    it('trusts only the exact immutable build for the current user', () => {
        notebookWidgetTrustLogic.actions.trustBuild(12, BUILD_HASH)

        expect(trustFor().buildTrusted).toBe(true)
        expect(trustFor({ buildHash: 'b'.repeat(64) }).buildTrusted).toBe(false)
        expect(trustFor({ userId: 13 }).buildTrusted).toBe(false)
        expect(trustFor({ buildHash: 'not-a-build-hash' }).buildTrusted).toBe(false)
    })

    it('keeps anonymous approval in the current session only', () => {
        notebookWidgetTrustLogic.actions.trustBuild(null, BUILD_HASH)

        expect(trustFor({ userId: null }).buildTrusted).toBe(true)
        expect(trustFor({ userId: 12 }).buildTrusted).toBe(false)
        expect(notebookWidgetTrustLogic.values.trustByUser).toEqual({})
    })
})
