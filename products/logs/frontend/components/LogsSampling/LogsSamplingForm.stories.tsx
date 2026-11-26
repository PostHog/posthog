import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { LogsExclusionRuleRuleTypeEnumApi, LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsSamplingForm } from './LogsSamplingForm'
import { logsSamplingFormLogic } from './logsSamplingFormLogic'

const REQUIRE_SECRET_KEY_RULE: LogsSamplingRuleApi = {
    id: '0192a5b0-0000-7000-8000-0000000000dd',
    name: 'Drop logs sent with the project token',
    enabled: true,
    priority: 0,
    rule_type: LogsExclusionRuleRuleTypeEnumApi.RequireSecretKey,
    config: {},
    version: 1,
    created_by: 1,
    created_at: '2026-11-20T09:00:00Z',
    updated_at: null,
}

const meta: Meta = {
    title: 'Logs/LogsSamplingForm',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-11-25',
    },
}
export default meta

type Story = StoryObj<{}>

export const RequireSecretKey: Story = {
    render: () => (
        <BindLogic logic={logsSamplingFormLogic} props={{ rule: REQUIRE_SECRET_KEY_RULE }}>
            <LogsSamplingForm />
        </BindLogic>
    ),
}
