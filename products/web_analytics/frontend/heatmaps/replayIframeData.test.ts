import { gzipSync, strFromU8, strToU8 } from 'fflate'

import {
    ReplayIframeData,
    ReplayIframeDatakeyPrefix as PREFIX,
    getStoredRecordingBackground,
    persistReplayIframeData,
} from './replayIframeData'

describe('replayIframeData', () => {
    const data: ReplayIframeData = {
        html: '<body>snapshot</body>',
        width: 100,
        height: 200,
        startDateTime: undefined,
        url: 'https://e',
    }

    // gzipped bytes held as a latin1 string, matching how persistReplayIframeData writes them
    const storeCompressed = (key: string, json: string): void => {
        localStorage.setItem(key, strFromU8(gzipSync(strToU8(json)), true))
    }

    const prefixedKeys = (): string[] => Object.keys(localStorage).filter((k) => k.startsWith(PREFIX))

    beforeEach(() => {
        localStorage.clear()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('round-trips a snapshot through compression, pruning older ones', () => {
        localStorage.setItem(`${PREFIX}stale`, '{}')

        const key = persistReplayIframeData(data)

        expect(key).not.toBeNull()
        expect(prefixedKeys()).toEqual([key])
        expect(getStoredRecordingBackground(key)).toEqual(data)
    })

    it('stores a snapshot far larger than the old character cap', () => {
        const large: ReplayIframeData = { ...data, html: `<body>${'x'.repeat(5_000_000)}</body>` }

        const key = persistReplayIframeData(large)

        expect(key).not.toBeNull()
        expect(getStoredRecordingBackground(key)).toEqual(large)
    })

    it('recovers on the next write after a rejected one, having pruned first', () => {
        localStorage.setItem(`${PREFIX}previous`, 'x')
        const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => {
            throw new DOMException('quota', 'QuotaExceededError')
        })

        expect(persistReplayIframeData(data)).toBeNull()
        expect(prefixedKeys()).toEqual([]) // the stale snapshot was pruned before the failed write

        setItem.mockRestore()
        const key = persistReplayIframeData(data)
        expect(key).not.toBeNull()
        expect(getStoredRecordingBackground(key)).toEqual(data)
    })

    it.each([
        ['not gzip data', (key: string) => localStorage.setItem(key, 'not gzip data')],
        ['malformed json', (key: string) => storeCompressed(key, '{not json')],
        ['a snapshot missing its dimensions', (key: string) => storeCompressed(key, '{"html":"<body>x</body>"}')],
        ['a blank snapshot', (key: string) => storeCompressed(key, '{"html":"  ","width":1,"height":2}')],
    ])('reads %s as null', (_name, store) => {
        store('stored')

        expect(getStoredRecordingBackground('stored')).toBeNull()
    })

    it('reads an absent snapshot as null', () => {
        expect(getStoredRecordingBackground(null)).toBeNull()
        expect(getStoredRecordingBackground('never-written')).toBeNull()
    })
})
