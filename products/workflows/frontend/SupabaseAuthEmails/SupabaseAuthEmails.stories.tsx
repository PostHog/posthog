import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type {
    SupabaseAuthEmailSettingsApi,
    SupabaseEmailTypeApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { SupabaseAuthEmails } from './SupabaseAuthEmails'
import { supabaseAuthEmailsLogic } from './supabaseAuthEmailsLogic'

const EMAIL_TYPES: SupabaseEmailTypeApi[] = [
    { value: 'signup', label: 'Confirm sign up', has_starter_template: true },
    { value: 'invite', label: 'Invite user', has_starter_template: true },
    { value: 'magiclink', label: 'Magic link', has_starter_template: true },
    { value: 'recovery', label: 'Reset password', has_starter_template: true },
    { value: 'password_changed_notification', label: 'Password changed', has_starter_template: false },
]

const notConnected: SupabaseAuthEmailSettingsApi = {
    supabase_url: '',
    has_hook_secret: false,
    templates: {},
    hook_url: 'https://us.posthog.com/webhooks/messaging/supabase/1/send-email',
    email_types: EMAIL_TYPES,
}

const connected: SupabaseAuthEmailSettingsApi = {
    ...notConnected,
    supabase_url: 'https://abcdefgh.supabase.co',
    has_hook_secret: true,
    templates: {
        signup: '0190a1b2-0000-7000-8000-000000000001',
        magiclink: '0190a1b2-0000-7000-8000-000000000002',
        recovery: '0190a1b2-0000-7000-8000-000000000003',
    },
}

const templates = {
    count: 3,
    next: null,
    previous: null,
    results: [
        ['0190a1b2-0000-7000-8000-000000000001', 'Supabase: confirm sign up'],
        ['0190a1b2-0000-7000-8000-000000000002', 'Supabase: magic link'],
        ['0190a1b2-0000-7000-8000-000000000003', 'Supabase: reset password'],
    ].map(([id, name]) => ({ id, name, transactional_hog_flow_id: id, sensitive: true, deleted: false })),
}

const meta: Meta = {
    title: 'Products/Workflows/SupabaseAuthEmails',
    component: SupabaseAuthEmails,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        testOptions: { waitForSelector: '[data-attr="workflows-supabase-auth-emails-open-setup"]' },
    },
}
export default meta

type StoryProps = { settings: SupabaseAuthEmailSettingsApi; setupOpen?: boolean }

const Template: StoryFn<StoryProps> = ({ settings, setupOpen }) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/messaging_supabase_auth_emails/settings/': settings,
            '/api/projects/:team_id/messaging_templates/': templates,
        },
    })
    const { openSetup } = useActions(supabaseAuthEmailsLogic)
    useEffect(() => {
        if (setupOpen) {
            openSetup()
        }
    }, [setupOpen, openSetup])
    return <SupabaseAuthEmails />
}

export const NotConnected = Template.bind({})
NotConnected.args = { settings: notConnected }

export const Connected = Template.bind({})
Connected.args = { settings: connected }

export const SetupOpen = Template.bind({})
SetupOpen.args = { settings: connected, setupOpen: true }
SetupOpen.parameters = {
    // The modal renders in a portal outside the story root, so only a fullscreen snapshot captures it.
    layout: 'fullscreen',
    testOptions: {
        waitForSelector: '[data-attr="workflows-supabase-auth-emails-url"]',
        // Tall enough that the modal doesn't scroll, so the snapshot shows all of it.
        viewport: { width: 1280, height: 1600 },
    },
}
