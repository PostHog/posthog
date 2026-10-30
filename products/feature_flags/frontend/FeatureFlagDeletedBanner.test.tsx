import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagDeletedBanner, FeatureFlagDeletedBannerProps } from './FeatureFlagDeletedBanner'

type BannerFlag = FeatureFlagDeletedBannerProps['flag']

const deletedFlag: BannerFlag = { deleted: true, archived: false, can_edit: true, filters: { groups: [] } }

const deletedCohortCondition = {
    key: 'id',
    type: PropertyFilterType.Cohort,
    operator: PropertyOperator.In,
    value: 5,
    cohort_name: 'Frequent buyers',
    cohort_deleted: true,
} as AnyPropertyFilter

const flagWithDeletedCohort: BannerFlag = {
    ...deletedFlag,
    filters: { groups: [{ properties: [deletedCohortCondition], rollout_percentage: 100 }] },
}

// LemonBanner renders its action twice, once per layout.
function restoreButtons(): NodeListOf<HTMLButtonElement> {
    return document.querySelectorAll<HTMLButtonElement>('[data-attr="restore-feature-flag-banner"]')
}

describe('FeatureFlagDeletedBanner', () => {
    let onRestore: jest.Mock

    function renderBanner(flag: BannerFlag): void {
        render(
            <Provider>
                <FeatureFlagDeletedBanner flag={flag} onRestore={onRestore} restoreLoading={false} />
            </Provider>
        )
    }

    beforeEach(() => {
        initKeaTests()
        onRestore = jest.fn()
    })

    afterEach(() => {
        cleanup()
    })

    it('lets an editor restore the flag', async () => {
        renderBanner(deletedFlag)

        expect(screen.getByText(/This feature flag is deleted\. .* Restore it to use it again\./)).toBeInTheDocument()
        await userEvent.click(restoreButtons()[0])
        expect(onRestore).toHaveBeenCalledTimes(1)
    })

    it.each([
        {
            state: 'a viewer',
            flag: { ...deletedFlag, can_edit: false },
            text: 'Ask someone with edit access to restore it.',
        },
        {
            state: 'a flag on the new config format',
            flag: { ...deletedFlag, filters: { version: 2, rules: [] } as unknown as FeatureFlagType['filters'] },
            text: 'Restoring is not available for this flag yet.',
        },
    ])('offers no restore to $state', ({ flag, text }) => {
        renderBanner(flag)

        expect(screen.getByText(text, { exact: false })).toBeInTheDocument()
        expect(restoreButtons()).toHaveLength(0)
    })

    it('blocks the restore while a release condition targets a deleted cohort', () => {
        renderBanner(flagWithDeletedCohort)

        expect(restoreButtons()[0]).toHaveAttribute('aria-disabled', 'true')
    })

    it('allows the restore of an archived flag, because unarchiving checks the cohorts', () => {
        renderBanner({ ...flagWithDeletedCohort, archived: true })

        expect(restoreButtons()[0]).toHaveAttribute('aria-disabled', 'false')
    })

    it('renders nothing for a flag that is not deleted', () => {
        renderBanner({ ...deletedFlag, deleted: false })

        expect(screen.queryByText(/is deleted/)).not.toBeInTheDocument()
    })
})
