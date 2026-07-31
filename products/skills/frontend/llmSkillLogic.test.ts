import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { llmSkillLogic } from './llmSkillLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { error: jest.fn(), success: jest.fn(), info: jest.fn() },
}))

describe('llmSkillLogic file uploads', () => {
    let logic: ReturnType<typeof llmSkillLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = llmSkillLogic({ skillName: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    const upload = async (files: File[]): Promise<void> => {
        await expectLogic(logic, () => logic.actions.addUploadedFiles(files)).toFinishAllListeners()
    }

    it('adds uploaded files to the form with inferred content types', async () => {
        await upload([new File(['print("hi")'], 'setup.py'), new File(['# Guide'], 'guide.md')])

        expect(logic.values.skillForm.files).toEqual([
            { path: 'setup.py', content: 'print("hi")', content_type: 'text/x-python' },
            { path: 'guide.md', content: '# Guide', content_type: 'text/markdown' },
        ])
    })

    it('re-uploading a path replaces its row, but a replayed File object does not clobber later edits', async () => {
        const firstUpload = new File(['v1'], 'notes.txt')
        await upload([firstUpload])

        logic.actions.setSkillFormValues({
            files: [{ path: 'notes.txt', content: 'edited by hand', content_type: 'text/plain' }],
        })

        // LemonFileInput replays previously selected File objects alongside new ones
        await upload([firstUpload, new File(['extra'], 'extra.txt')])
        expect(logic.values.skillForm.files).toEqual([
            { path: 'notes.txt', content: 'edited by hand', content_type: 'text/plain' },
            { path: 'extra.txt', content: 'extra', content_type: 'text/plain' },
        ])

        await upload([new File(['v2'], 'notes.txt')])
        expect(logic.values.skillForm.files).toEqual([
            { path: 'notes.txt', content: 'v2', content_type: 'text/plain' },
            { path: 'extra.txt', content: 'extra', content_type: 'text/plain' },
        ])
    })

    it('rejects oversized and binary files with an error toast but keeps valid ones', async () => {
        await upload([
            new File([new ArrayBuffer(1_000_001)], 'big.txt'),
            new File(['\u0000binary'], 'nul.txt'),
            new File([new Uint8Array([0xc3, 0x28])], 'invalid-utf8.txt'),
            new File(['has a \ufffd char'], 'replacement.txt'),
            new File(['ok'], 'ok.txt'),
        ])

        expect(logic.values.skillForm.files).toEqual([
            { path: 'replacement.txt', content: 'has a \ufffd char', content_type: 'text/plain' },
            { path: 'ok.txt', content: 'ok', content_type: 'text/plain' },
        ])
        expect(jest.mocked(lemonToast.error).mock.calls.map(([message]) => message)).toEqual([
            "Couldn't add big.txt: files must be 1 MB or smaller",
            "Couldn't add nul.txt: only text files are supported",
            "Couldn't add invalid-utf8.txt: only text files are supported",
        ])
    })
})
