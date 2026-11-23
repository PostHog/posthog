import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutReportActionsSection } from './ScoutReportActionsSection'

const CONFIG: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-pr-follow-up',
    description: 'Pull request follow-up',
    scout_origin: 'custom',
    scout_role: 'specialist',
    owners: [],
    enabled: true,
    status: 'active',
    pause_reason: null,
    managed_by: 'team',
    deprecation: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
    write_scopes: [],
    report_actions: [],
    max_report_actions_per_day: 3,
    allowed_mcp_tools: null,
    tool_preset: null,
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    status_changed_by: null,
    auto_pause_exempt: false,
    lifecycle_locked: false,
    network_access: 'trusted',
    model: null,
    custom_image_id: null,
    precheck_query: null,
    precheck_disabled: false,
    effective_precheck_query: null,
    precheck_query_source: 'off',
    last_precheck_at: null,
    last_precheck_outcome: null,
    last_precheck_row_count: null,
    tags: [],
    source_product: null,
    source_id: null,
    created_at: '2026-07-21T12:00:00Z',
    updated_at: '2026-07-21T12:00:00Z',
}

describe('ScoutReportActionsSection', () => {
    beforeEach(() => {
        initKeaTests()
    })
    afterEach(cleanup)

    it.each([
        { name: 'a scout with no grant', reportActions: [], emit: true, shown: ['None'], dryRunNote: false },
        {
            name: 'a scout with a grant',
            reportActions: ['make_it_green', 'resolve_conflicts'],
            emit: true,
            shown: ['Make it green', 'Resolve conflicts'],
            dryRunNote: false,
        },
        // A dry run never holds the grant, so a header that reads like a live scout's would promise
        // agent runs the next run cannot start.
        {
            name: 'a dry-run scout with a grant',
            reportActions: ['make_it_green'],
            emit: false,
            shown: ['Make it green'],
            dryRunNote: true,
        },
        // A grantable action the backend adds before this form knows it must still show.
        {
            name: 'a scout holding an action the form has no label for',
            reportActions: ['fix_flaky_tests'],
            emit: true,
            shown: ['fix_flaky_tests'],
            dryRunNote: false,
        },
    ])('shows what $name holds without opening the section', ({ reportActions, emit, shown, dryRunNote }) => {
        render(
            <ScoutReportActionsSection
                config={{ ...CONFIG, emit, report_actions: reportActions }}
                onUpdate={jest.fn()}
            />
        )

        for (const text of shown) {
            expect(screen.getByText(text)).toBeInTheDocument()
        }
        expect(screen.queryByText('Inactive during dry run') !== null).toBe(dryRunNote)
    })

    it.each([
        {
            name: 'turning on an action',
            stored: [],
            edit: () => fireEvent.click(screen.getByLabelText('Let this scout start make it green')),
            sent: { report_actions: ['make_it_green'] },
        },
        {
            // An action the form has no switch for must ride along, or a save here revokes it.
            name: 'turning on an action next to one the form has no switch for',
            stored: ['fix_flaky_tests'],
            edit: () => fireEvent.click(screen.getByLabelText('Let this scout start make it green')),
            sent: { report_actions: ['fix_flaky_tests', 'make_it_green'] },
        },
        {
            name: 'changing the daily limit',
            stored: [],
            edit: () =>
                fireEvent.change(screen.getByLabelText('Daily report action limit'), { target: { value: '5' } }),
            sent: { max_report_actions_per_day: 5 },
        },
    ])('stages $name and sends it only on the save button', ({ stored, edit, sent }) => {
        // Each action starts an agent run that acts as a person, so a stray click must not widen the grant.
        const onUpdate = jest.fn()
        render(<ScoutReportActionsSection config={{ ...CONFIG, report_actions: stored }} onUpdate={onUpdate} />)
        fireEvent.click(screen.getByText('Report actions'))

        edit()
        expect(onUpdate).not.toHaveBeenCalled()

        fireEvent.click(screen.getByText('Save report actions'))
        expect(onUpdate).toHaveBeenCalledWith('config-1', sent)
    })

    it('goes back to the saved grant when the save is rejected', () => {
        // The fleet logic shows the API's refusal and keeps the server's config, so the section must
        // follow that config rather than keep showing the grant the server refused.
        const onUpdate = jest.fn()
        const { rerender } = render(<ScoutReportActionsSection config={CONFIG} onUpdate={onUpdate} />)
        fireEvent.click(screen.getByText('Report actions'))
        fireEvent.click(screen.getByLabelText('Let this scout start make it green'))
        fireEvent.click(screen.getByText('Save report actions'))

        rerender(<ScoutReportActionsSection config={{ ...CONFIG }} onUpdate={onUpdate} />)

        expect(screen.getByLabelText('Let this scout start make it green')).not.toBeChecked()
        expect(screen.getByText('None')).toBeInTheDocument()
    })

    it('refuses to save a daily limit outside the range the API accepts', () => {
        const onUpdate = jest.fn()
        render(<ScoutReportActionsSection config={CONFIG} onUpdate={onUpdate} />)
        fireEvent.click(screen.getByText('Report actions'))

        fireEvent.change(screen.getByLabelText('Daily report action limit'), { target: { value: '21' } })
        fireEvent.click(screen.getByText('Save report actions'))

        expect(onUpdate).not.toHaveBeenCalled()
    })
})
