import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { codeEmailLogic } from './codeEmailLogic'
import { SourceRow } from './SourceRow'

describe('SourceRow', () => {
    let logic: ReturnType<typeof codeEmailLogic.build>

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([
        [
            'GitHub',
            'https://github.com/acme/web/blob/feature/receipts/src/emails/receipt.tsx',
            'receipt.tsx',
            'acme/web',
        ],
        [
            'GitLab',
            'https://gitlab.com/acme/shop/-/blob/release/2026/app/mailers/receipt.rb',
            'receipt.rb',
            'acme/shop',
        ],
    ])(
        'shows a %s file on a branch with a slash by its name, linking the whole link',
        async (_host, url, name, repo) => {
            const codeEmail: CodeEmailApi = {
                id: 'email-id',
                key: 'receipt',
                hog_flow_id: 'flow-id',
                description: '',
                tags: [],
                sensitive: false,
                source_url: url,
                created_at: '2026-01-01T00:00:00Z',
                user_access_level: 'editor',
            }
            useMocks({ get: { '/api/projects/:team_id/transactional_code_emails/:id/': codeEmail } })
            initKeaTests()
            logic = codeEmailLogic({ id: 'email-id' })
            logic.mount()
            render(
                <Provider>
                    <BindLogic logic={codeEmailLogic} props={{ id: 'email-id' }}>
                        <SourceRow />
                    </BindLogic>
                </Provider>
            )

            const repoLink = await screen.findByText(repo)
            expect(repoLink.closest('[data-attr=code-email-source-row]')?.textContent).toEqual(`${name}in ${repo}`)
            expect(screen.getByText(name).closest('a')).toHaveAttribute('href', url)
        }
    )
})
