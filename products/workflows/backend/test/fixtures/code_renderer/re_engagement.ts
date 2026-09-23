// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - Pass-through steps: wait_for_a_click (Wait for a click), nudge_by_email (Nudge by email), text_them (Text them).
// - exit_node: The path after "Nudge by email" does not rejoin the workflow. The steps it leads to are dropped.
// - nudge_by_email: The path after "Text them" does not rejoin the workflow. The steps it leads to are dropped.

import { onEvent, path, step, workflow } from '@posthog/workflows'

export const reEngagement = workflow({
    key: 're-engagement',
    name: 'Re-engagement',
    status: 'active',
    on: onEvent({ event: 'trial started' }),
    steps: path(
        step({
            name: 'Wait for a click',
            type: 'wait_until_condition',
            config: {
                condition: {
                    filters: {
                        events: [{ id: '$autocapture', name: '$autocapture', type: 'events', order: 0 }],
                    },
                },
                max_wait_duration: '3d',
            },
            branches: [
                path(
                    step({
                        name: 'Nudge by email',
                        type: 'function_email',
                        config: {
                            template_id: 'template-email',
                            inputs: {
                                email: {
                                    value: {
                                        from: { integrationId: 7, integrationIds: [7] },
                                        to: { email: '{person.properties.email}' },
                                        subject: 'Your trial ends soon',
                                        text: 'Come back and finish setup.',
                                        html: '<p>Come back and finish setup.</p>',
                                        design: {
                                            counters: { u_row: 1, u_column: 1, u_content_text: 1 },
                                            schemaVersion: 16,
                                            body: {
                                                id: 'body-1',
                                                headers: [],
                                                footers: [],
                                                rows: [
                                                    {
                                                        id: 'row-1',
                                                        cells: [1],
                                                        columns: [
                                                            {
                                                                id: 'column-1',
                                                                contents: [
                                                                    {
                                                                        id: 'text-1',
                                                                        type: 'text',
                                                                        values: { text: '<p>Come back and finish setup.</p>', fontSize: '16px' },
                                                                    },
                                                                ],
                                                                values: {},
                                                            },
                                                        ],
                                                        values: {},
                                                    },
                                                ],
                                                values: {},
                                            },
                                        },
                                    },
                                    order: 0,
                                },
                            },
                        },
                    }),
                ),
            ],
        }),
        step({
            name: 'Text them',
            type: 'function_sms',
            config: {
                template_id: 'template-twilio',
                inputs: {
                    to: { value: '{person.properties.phone}', order: 0 },
                    body: { value: 'Your trial ends soon. Come back and finish setup.', order: 1 },
                },
                message_category_type: 'marketing',
            },
        }),
    ),
    exit: { reason: 'Done' },
})
