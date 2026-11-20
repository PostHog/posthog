import {
    OwnEmailAction,
    SandboxEmailAction,
    ownOnlySettings,
    sandboxRecipient,
    toOwnEmailAction,
    toSandboxAction,
    withSandboxEmail,
} from './emailStepVariants'

const content = {
    to: { email: '{{ person.properties.email }}', name: 'Ada' },
    subject: 'Welcome',
    preheader: 'Hi there',
    text: 'Hello',
    html: '<p>Hello</p>',
    design: { body: { rows: [] } },
}

const graphFields = {
    id: 'action_function_email_1',
    name: 'Welcome email',
    description: 'Says hello',
    on_error: 'continue' as const,
    created_at: 1,
    updated_at: 2,
    filters: { properties: [{ key: 'plan', value: 'free', operator: 'exact', type: 'person' }] },
    output_variable: { key: 'welcome_result' },
}

function ownAction(value: Record<string, unknown> = {}, config: Record<string, unknown> = {}): OwnEmailAction {
    return {
        ...graphFields,
        type: 'function_email',
        config: {
            template_id: 'template-email',
            message_category_id: 'category-1',
            message_category_type: 'marketing',
            tracking_enabled: false,
            utm_tags_enabled: true,
            ...config,
            inputs: {
                email: {
                    templating: 'liquid',
                    bytecode: ['_H', 1],
                    value: { ...content, from: { integrationId: 7 }, replyTo: '', cc: '', bcc: '', ...value },
                },
            },
        },
    } as OwnEmailAction
}

describe('email step variants', () => {
    it('builds a sandbox step that keeps the graph fields and content and drops every own-sender field', () => {
        expect(toSandboxAction(ownAction({ replyTo: 'support@example.com', cc: 'a@example.com' }))).toEqual({
            ...graphFields,
            type: 'email_sandbox',
            config: {
                message_category_id: 'category-1',
                message_category_type: 'marketing',
                inputs: { email: { templating: 'liquid', value: content } },
            },
        })
    })

    it('builds an own email step with the chosen sender and the same content', () => {
        const sandbox = toSandboxAction(ownAction())

        expect(toOwnEmailAction(sandbox, 42)).toEqual({
            ...graphFields,
            type: 'function_email',
            config: {
                template_id: 'template-email',
                message_category_id: 'category-1',
                message_category_type: 'marketing',
                inputs: { email: { templating: 'liquid', value: { ...content, from: { integrationId: 42 } } } },
            },
        })
    })

    it('leaves out optional content a sandbox step never had', () => {
        const sandbox = {
            ...graphFields,
            type: 'email_sandbox',
            config: { inputs: { email: { templating: 'hog', value: { to: { email: 'a@example.com' } } } } },
        } as SandboxEmailAction

        expect(toOwnEmailAction(sandbox, 3).config).toEqual({
            template_id: 'template-email',
            inputs: {
                email: { templating: 'hog', value: { to: { email: 'a@example.com' }, from: { integrationId: 3 } } },
            },
        })
    })

    it('keeps an edit to a sandbox step to the fields a sandbox step stores', () => {
        const sandbox = toSandboxAction(ownAction())

        const edited = withSandboxEmail(sandbox, {
            ...content,
            to: '',
            subject: 'Updated',
            from: { integrationId: 7 },
            replyTo: 'support@example.com',
            cc: 'a@example.com',
        })

        expect(edited.config.inputs.email.value).toEqual({ ...content, subject: 'Updated' })
        expect(edited.config.message_category_id).toEqual('category-1')
    })

    it('reads and sets the recipient of a sandbox draft saved without one', () => {
        const draft = {
            ...toSandboxAction(ownAction()),
            config: { inputs: { email: { value: {} } } },
        } as SandboxEmailAction

        const edited = withSandboxEmail(draft, { to: { email: 'member@example.com' } })

        expect(sandboxRecipient(draft)).toEqual('')
        expect(sandboxRecipient(edited)).toEqual('member@example.com')
    })

    it.each([
        ['nothing for a plain sender', {}, {}, []],
        ['a From override', { from: { integrationId: 7, email: 'news@example.com' } }, {}, ['sender_override']],
        ['a display name override', { from: { integrationId: 7, name: 'News' } }, {}, ['sender_override']],
        ['several senders', { from: { integrationId: 7, integrationIds: [7, 8] } }, {}, ['several_senders']],
        ['a Reply-To', { replyTo: 'support@example.com' }, {}, ['reply_to']],
        ['CC or BCC', { cc: '', bcc: 'audit@example.com' }, {}, ['cc_bcc']],
        ['tracking turned off', {}, { tracking_enabled: false }, ['tracking_off']],
        ['UTM tags', {}, { utm_tags_enabled: true }, ['utm_tags']],
    ])('lists %s as settings the sandbox sender drops', (_name, value, config, expected) => {
        expect(
            ownOnlySettings(ownAction(value, { tracking_enabled: true, utm_tags_enabled: false, ...config }))
        ).toEqual(expected)
    })
})
