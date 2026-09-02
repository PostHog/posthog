import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { makeReport } from '../../__mocks__/inboxMocks'
import { ValidateLocallySection } from './ValidateLocallySection'

const meta: Meta<typeof ValidateLocallySection> = {
    title: 'Scenes-App/Inbox/ValidateLocallySection',
    component: ValidateLocallySection,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof ValidateLocallySection>

const PGANALYZE_PROMPT = `Check a missing-index finding on \`posthog_featureflag\` before trusting the fix.

Recreate:
1. Open \`posthog/models/feature_flag/flag_matching.py\` and find the flag lookup that filters on \`team_id\` and \`active\`.
2. Run the query against a read replica with \`EXPLAIN (ANALYZE, BUFFERS)\`.
3. The plan reads the whole relation. pganalyze reports it as the slowest statement on the primary.

Test:
1. Save the plan you just captured.
2. Build the candidate index on the replica with \`CREATE INDEX CONCURRENTLY\`.
3. Re-run the same \`EXPLAIN\` and compare. If the planner still scans the relation, the index is the wrong shape.
4. Run \`hogli test posthog/models/feature_flag\` before opening anything.`

export const WithPrompt: Story = {
    render: () => (
        <ValidateLocallySection
            report={makeReport({
                title: 'fix(flags): index the flag lookup pganalyze flagged',
                validation_prompt: PGANALYZE_PROMPT,
            })}
            reportUrl="https://app.posthog.com/project/1/inbox/reports/report-1"
        />
    ),
    // Collapsed at rest, so the snapshot would otherwise be of a header row with nothing under it.
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Validate locally'))
    },
}
