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

    const prefixedKeys = (): string[] => Object.keys(localStorage).filter((k) => k.startsWith(PREFIX))

    beforeEach(() => {
        localStorage.clear()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('prunes older snapshots once the new one is written', () => {
        localStorage.setItem(`${PREFIX}stale`, '{}')

        const key = persistReplayIframeData(data)

        expect(key).not.toBeNull()
        expect(prefixedKeys()).toEqual([key])
        expect(getStoredRecordingBackground(key)).toEqual(data)
    })

    it('keeps the previous snapshot when the write is rejected', () => {
        localStorage.setItem(`${PREFIX}previous`, '{"html":"<body>old</body>"}')
        jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new DOMException('quota', 'QuotaExceededError')
        })

        expect(persistReplayIframeData(data)).toBeNull()
        expect(prefixedKeys()).toEqual([`${PREFIX}previous`])
    })

    it.each([
        ['malformed json', '{not json'],
        ['a snapshot missing its dimensions', '{"html":"<body>x</body>"}'],
        ['a blank snapshot', '{"html":"  ","width":1,"height":2}'],
    ])('reads %s as null', (_name, stored) => {
        localStorage.setItem('stored', stored)

        expect(getStoredRecordingBackground('stored')).toBeNull()
    })

    it('reads an absent snapshot as null', () => {
        expect(getStoredRecordingBackground(null)).toBeNull()
        expect(getStoredRecordingBackground('never-written')).toBeNull()
    })
})
