import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { ApiError } from '~/lib/api-error'
import { initKeaTests } from '~/test/init'

import {
    llmSkillsNameFilesRetrieve,
    llmSkillsNamePartialUpdate,
    llmSkillsResolveNameRetrieve,
} from 'products/skills/frontend/generated/api'
import type { LLMSkillApi, LLMSkillResolveResponseApi } from 'products/skills/frontend/generated/api.schemas'

import { SkillMode, llmSkillLogic } from './llmSkillLogic'
import type { ResolvedLLMSkill } from './llmSkillLogic'
import type { SkillFileUpload } from './skillFileUpload'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { error: jest.fn(), success: jest.fn(), info: jest.fn() },
}))

jest.mock('products/skills/frontend/generated/api', () => ({
    llmSkillsCreate: jest.fn(),
    llmSkillsNameArchiveCreate: jest.fn(),
    llmSkillsNameFilesRetrieve: jest.fn(),
    llmSkillsNamePartialUpdate: jest.fn(),
    llmSkillsResolveNameRetrieve: jest.fn(),
}))

const mockPartialUpdate = llmSkillsNamePartialUpdate as jest.MockedFunction<typeof llmSkillsNamePartialUpdate>
const mockResolve = llmSkillsResolveNameRetrieve as jest.MockedFunction<typeof llmSkillsResolveNameRetrieve>
const mockFilesRetrieve = llmSkillsNameFilesRetrieve as jest.MockedFunction<typeof llmSkillsNameFilesRetrieve>

const MOCK_FILE = { path: 'scripts/run.sh', content: 'echo hi', content_type: 'text/x-shellscript' }

const mockSkill = {
    id: 'skill-version-2',
    name: 'my-test-skill',
    description: 'Does useful things.',
    body: '# My skill',
    license: '',
    compatibility: '',
    allowed_tools: [],
    metadata: {},
    version: 2,
    version_description: null,
    latest_version: 2,
    version_count: 2,
    first_version_created_at: '2024-01-01T00:00:00Z',
    is_latest: true,
    deleted: false,
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
    created_by: { id: 1, email: 'test@example.com' },
    files: [{ path: MOCK_FILE.path, content_type: MOCK_FILE.content_type }],
    body_total_length: 10,
    body_next_offset: null,
    versions: [
        {
            id: 'skill-version-2',
            version: 2,
            version_description: null,
            created_by: { id: 1, email: 'test@example.com' },
            created_at: '2024-01-02T00:00:00Z',
            is_latest: true,
        },
        {
            id: 'skill-version-1',
            version: 1,
            version_description: null,
            created_by: { id: 1, email: 'test@example.com' },
            created_at: '2024-01-01T00:00:00Z',
            is_latest: false,
        },
    ],
    has_more: false,
} as unknown as ResolvedLLMSkill

describe('llmSkillLogic', () => {
    describe('publish flow', () => {
        let logic: ReturnType<typeof llmSkillLogic.build>

        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            mockFilesRetrieve.mockResolvedValue(MOCK_FILE)
        })

        afterEach(() => {
            logic?.unmount()
        })

        const resolveResponse = (skill: ResolvedLLMSkill): LLMSkillResolveResponseApi => {
            const { versions, has_more, ...skillFields } = skill
            return { skill: skillFields, versions, has_more } as unknown as LLMSkillResolveResponseApi
        }

        it('opens the review modal on requestPublish and sends the version description on publish', async () => {
            mockResolve.mockResolvedValue(resolveResponse(mockSkill))
            mockPartialUpdate.mockResolvedValue({
                ...mockSkill,
                id: 'skill-version-3',
                version: 3,
                latest_version: 3,
                version_description: 'Added a troubleshooting section',
            } as unknown as LLMSkillApi)

            logic = llmSkillLogic({ skillName: 'my-test-skill' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSkillSuccess'])

            logic.actions.setMode(SkillMode.Edit)
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setSkillFormValues({ body: '# My skill, improved' })

            logic.actions.requestPublish()
            expect(logic.values.isPublishReviewOpen).toBe(true)
            expect(mockPartialUpdate).not.toHaveBeenCalled()

            logic.actions.setVersionDescription('Added a troubleshooting section')
            logic.actions.submitSkillForm()
            await expectLogic(logic).toDispatchActions(['submitSkillFormSuccess'])

            expect(mockPartialUpdate).toHaveBeenCalledWith(
                expect.anything(),
                'my-test-skill',
                expect.objectContaining({
                    body: '# My skill, improved',
                    base_version: 2,
                    version_description: 'Added a troubleshooting section',
                })
            )
            // Untouched files are omitted, so the server carries the current latest's files
            // forward instead of overwriting them with this editor's stale copy.
            expect(mockPartialUpdate.mock.calls[0]?.[2]?.files).toBeUndefined()
            expect(logic.values.isPublishReviewOpen).toBe(false)
            expect(logic.values.mode).toBe(SkillMode.View)
        })

        it('preserves form edits and advances the base version on a publish conflict', async () => {
            const conflictingLatest = {
                ...mockSkill,
                id: 'skill-version-3',
                body: 'Someone else edited this skill.',
                version: 3,
                latest_version: 3,
                version_count: 3,
            }

            mockResolve
                .mockResolvedValueOnce(resolveResponse(mockSkill))
                .mockResolvedValue(resolveResponse(conflictingLatest))
            mockPartialUpdate.mockRejectedValue(
                new ApiError('conflict', 409, undefined, { detail: 'The skill changed since you opened it.' })
            )

            logic = llmSkillLogic({ skillName: 'my-test-skill' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSkillSuccess'])

            logic.actions.setMode(SkillMode.Edit)
            logic.actions.setSkillFormValues({ body: 'My in-progress edit.' })

            logic.actions.submitSkillForm()
            await expectLogic(logic).toDispatchActions(['submitSkillFormFailure'])

            expect(logic.values.skillForm.body).toBe('My in-progress edit.')
            expect(logic.values.publishConflict).toEqual({ latestVersion: 3 })
            expect(logic.values.skill).toMatchObject({ latest_version: 3 })
            expect(logic.values.mode).toBe(SkillMode.Edit)
        })
    })

    describe('file uploads', () => {
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

        it('caps a folder drop at 200 files and says so instead of silently failing on publish', async () => {
            await upload(Array.from({ length: 205 }, (_, i) => asUpload(`content ${i}`, `references/file-${i}.txt`)))

            expect(logic.values.skillForm.files).toHaveLength(200)
            expect(logic.values.skillForm.files[199].path).toBe('references/file-199.txt')
            expect(jest.mocked(lemonToast.error)).toHaveBeenCalledWith(
                "Some files weren't added: a skill can have at most 200 bundled files"
            )
        })
    })
})
