import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { Form } from 'kea-forms'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonDialogLogic } from 'lib/lemon-ui/LemonDialog/lemonDialogLogic'

import { initKeaTests } from '~/test/init'

import { llmSkillsNameRetrieve } from 'products/skills/frontend/generated/api'
import type { LLMSkillApi } from 'products/skills/frontend/generated/api.schemas'

import { openPublishToCommunityDialog, publishToCommunityDisabledReason } from './skillSceneComponents'

jest.mock('products/skills/frontend/generated/api', () => ({
    llmSkillsNameRetrieve: jest.fn(),
}))

const mockRetrieve = llmSkillsNameRetrieve as jest.MockedFunction<typeof llmSkillsNameRetrieve>

type OpenFormConfig = Parameters<typeof LemonDialog.openForm>[0]

const MOCK_PREVIEW = {
    name: 'my-skill',
    version: 3,
    files: [
        { path: 'scripts/run.sh', content_type: 'text/x-shellscript', line_count: 1, char_count: 7 },
        { path: 'references/guide.md', content_type: 'text/markdown', line_count: 1, char_count: 7 },
    ],
} as unknown as LLMSkillApi

describe('skillSceneComponents', () => {
    let openFormSpy: jest.SpyInstance<void, [OpenFormConfig]>
    let dialogConfig: OpenFormConfig | undefined

    beforeEach(() => {
        initKeaTests()
        dialogConfig = undefined
        mockRetrieve.mockResolvedValue(MOCK_PREVIEW)
        openFormSpy = jest.spyOn(LemonDialog, 'openForm').mockImplementation((config) => {
            dialogConfig = config
        })
    })

    afterEach(() => {
        openFormSpy.mockRestore()
    })

    describe('publish to community dialog', () => {
        it('keeps the submit button disabled until the consent box is checked', () => {
            openPublishToCommunityDialog({ skillName: 'my-skill', githubLogin: null, onPublish: jest.fn() })

            expect(dialogConfig?.initialValues.consent).toBe(false)
            expect(dialogConfig?.title).toBe('Publish to the PostHog community?')
            expect(dialogConfig?.description).toBe(
                'All PostHog users can find and use this skill. Its contents will also be public on GitHub.'
            )
            expect(dialogConfig?.errors?.consent(false, {})).toBe(
                'Review the skill and confirm that you can share it publicly'
            )
            expect(dialogConfig?.errors?.consent(true, {})).toBeUndefined()
            expect(dialogConfig?.primaryButtonProps?.children).toBe('Publish to community')
        })

        it('names the destination and version, with the file list behind Review files', async () => {
            openPublishToCommunityDialog({ skillName: 'my-skill', githubLogin: null, onPublish: jest.fn() })

            render(
                <Provider>
                    <Form logic={lemonDialogLogic} props={{}} formKey="form">
                        {dialogConfig?.content as JSX.Element}
                    </Form>
                </Provider>
            )

            expect(screen.getByText('PostHog/community-skills')).toBeInTheDocument()
            await waitFor(() => expect(screen.getByText('v3')).toBeInTheDocument())
            expect(screen.queryByText('SKILL.md')).not.toBeInTheDocument()
            fireEvent.click(screen.getByText('Review files'))
            expect(screen.getByText('SKILL.md')).toBeInTheDocument()
            expect(screen.getByText('scripts/run.sh')).toBeInTheDocument()
            expect(screen.getByText('references/guide.md')).toBeInTheDocument()
        })
    })

    describe('publishToCommunityDisabledReason', () => {
        it.each([
            ['in flight', { publishing: true }, 'Publishing…'],
            ['no owners', { ownerUuids: [] }, 'Add an owner before you publish this skill'],
            ['not an owner', { currentUserUuid: 'other' }, "Only the skill's owners can publish it"],
            ['historical version', { isHistoricalVersion: true }, 'Switch to the latest version to publish'],
        ])('blocks publishing %s', (_label, overrides, expected) => {
            expect(
                publishToCommunityDisabledReason({
                    ownerUuids: ['me'],
                    currentUserUuid: 'me',
                    publishing: false,
                    ...overrides,
                })
            ).toBe(expected)
        })

        it('allows an owner to publish the latest version', () => {
            expect(
                publishToCommunityDisabledReason({
                    ownerUuids: ['me'],
                    currentUserUuid: 'me',
                    publishing: false,
                })
            ).toBeUndefined()
        })
    })
})
