import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { llmSkillLogic } from './llmSkillLogic'
import type { SkillFileUpload } from './skillFileUpload'

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

    const asUpload = (content: string, path: string): SkillFileUpload => ({
        path,
        file: new File([content], path.split('/').pop() ?? path),
    })

    const upload = async (files: SkillFileUpload[]): Promise<void> => {
        await expectLogic(logic, () => logic.actions.addUploadedFiles(files)).toFinishAllListeners()
    }

    it('adds uploaded files to the form, preserving folder paths and inferring content types', async () => {
        await upload([asUpload('print("hi")', 'scripts/setup.py'), asUpload('# Guide', 'references/guide.md')])

        expect(logic.values.skillForm.files).toEqual([
            { path: 'scripts/setup.py', content: 'print("hi")', content_type: 'text/x-python' },
            { path: 'references/guide.md', content: '# Guide', content_type: 'text/markdown' },
        ])
    })

    it('re-uploading a path replaces its row instead of duplicating it', async () => {
        await upload([asUpload('v1', 'notes.txt'), asUpload('extra', 'extra.txt')])
        await upload([asUpload('v2', 'notes.txt')])

        expect(logic.values.skillForm.files).toEqual([
            { path: 'notes.txt', content: 'v2', content_type: 'text/plain' },
            { path: 'extra.txt', content: 'extra', content_type: 'text/plain' },
        ])
    })

    it('rejects oversized, binary, and SKILL.md files with a toast but keeps valid ones', async () => {
        await upload([
            { path: 'big.txt', file: new File([new ArrayBuffer(1_000_001)], 'big.txt') },
            asUpload('\u0000binary', 'nul.txt'),
            { path: 'invalid-utf8.txt', file: new File([new Uint8Array([0xc3, 0x28])], 'invalid-utf8.txt') },
            asUpload('has a \ufffd char', 'replacement.txt'),
            asUpload('# My skill', 'Skill.md'),
            asUpload('ok', 'ok.txt'),
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
        expect(jest.mocked(lemonToast.info)).toHaveBeenCalledWith(
            "SKILL.md wasn't added as a bundled file. Its body belongs in the skill body field."
        )
    })

    it('caps a folder drop at 50 files and says so instead of silently failing on publish', async () => {
        await upload(Array.from({ length: 55 }, (_, i) => asUpload(`content ${i}`, `references/file-${i}.txt`)))

        expect(logic.values.skillForm.files).toHaveLength(50)
        expect(logic.values.skillForm.files[49].path).toBe('references/file-49.txt')
        expect(jest.mocked(lemonToast.error)).toHaveBeenCalledWith(
            "Some files weren't added: a skill can have at most 50 bundled files"
        )
    })
})
