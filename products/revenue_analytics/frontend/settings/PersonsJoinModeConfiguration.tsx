import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { RevenueAnalyticsPersonsJoinMode } from '~/queries/schema/schema-general'
import { PipelineTab } from '~/types'

export function PersonsJoinModeConfiguration(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const [personsJoinMode, setPersonsJoinMode] = useState<RevenueAnalyticsPersonsJoinMode>(
        currentTeam?.modifiers?.revenueAnalyticsPersonsJoinMode ??
            currentTeam?.default_modifiers?.revenueAnalyticsPersonsJoinMode ??
            RevenueAnalyticsPersonsJoinMode.ID
    )
    const [personsJoinModeCustom, setPersonsJoinModeCustom] = useState<string | null>(
        currentTeam?.modifiers?.revenueAnalyticsPersonsJoinModeCustom ??
            currentTeam?.default_modifiers?.revenueAnalyticsPersonsJoinModeCustom ??
            null
    )

    const updatePersonsJoinMode = (value: RevenueAnalyticsPersonsJoinMode): void => {
        setPersonsJoinMode(value)
        if (value !== RevenueAnalyticsPersonsJoinMode.CUSTOM) {
            setPersonsJoinModeCustom(null)
        }
    }

    const updatePersonsJoinModeCustom = (value: string): void => {
        setPersonsJoinModeCustom(value)
    }

    const save = (): void => {
        updateCurrentTeam({
            modifiers: {
                ...currentTeam?.modifiers,
                revenueAnalyticsPersonsJoinMode: personsJoinMode,
                revenueAnalyticsPersonsJoinModeCustom: personsJoinModeCustom,
            },
        })
    }

    const disabledReason =
        personsJoinMode === RevenueAnalyticsPersonsJoinMode.CUSTOM && !personsJoinModeCustom
            ? 'Custom field is required'
            : personsJoinMode === currentTeam?.modifiers?.revenueAnalyticsPersonsJoinMode &&
              personsJoinModeCustom === currentTeam?.modifiers?.revenueAnalyticsPersonsJoinModeCustom
            ? 'No changes to save'
            : null

    return (
        <div>
            <h3 className="mb-2">Join mode for persons</h3>
            <p className="mb-4">
                Choose how PostHog persons are joined to Revenue Analytics data. This will allow you to properly see how
                much revenue is associated with each person. We'll always connect the person's <code>distinct_id</code>{' '}
                in PostHog to "something" in your revenue collection system. This lets you choose what that "something"
                is, depending on how you identify these people in PostHog vs. that system.
            </p>

            <div className="flex flex-col gap-2 mb-4">
                <LemonRadio
                    value={personsJoinMode}
                    onChange={updatePersonsJoinMode}
                    options={[
                        {
                            value: RevenueAnalyticsPersonsJoinMode.ID,
                            label: 'ID',
                            description: (
                                <span className="text-sm font-normal">
                                    Match against the customer's ID in the revenue collection system. <br />
                                    For <Link to={urls.pipeline(PipelineTab.Sources)}>Stripe</Link>, this means
                                    connecting to the <code>cus_xxx</code> value. You'll need to alias all of your
                                    people in PostHog to include Stripe's <code>cus_xxx</code> value.
                                </span>
                            ),
                        },
                        {
                            value: RevenueAnalyticsPersonsJoinMode.EMAIL,
                            label: 'Email',
                            description: (
                                <span className="text-sm font-normal">
                                    Match against the customer's email in the revenue collection system. <br />
                                    You'll need to alias all of your people in PostHog to include the same email address
                                    as they have in your revenue collection system.
                                </span>
                            ),
                        },
                        {
                            value: RevenueAnalyticsPersonsJoinMode.CUSTOM,
                            label: 'Custom',
                            description: (
                                <span className="text-sm font-normal">
                                    Match against an arbitrary value in your Revenue Analytics customer's{' '}
                                    <code>metadata</code> property. <br />
                                    For <Link to={urls.pipeline(PipelineTab.Sources)}>Stripe</Link>, this implies
                                    storing this value on the <code>metadata</code> property on the{' '}
                                    <code>Customer</code> object.
                                </span>
                            ),
                        },
                    ]}
                    orientation="vertical"
                    radioPosition="center"
                />

                <LemonInput
                    className="ml-5 w-1/2"
                    value={personsJoinModeCustom || ''}
                    onChange={updatePersonsJoinModeCustom}
                    placeholder="Enter your custom field"
                    disabled={personsJoinMode !== RevenueAnalyticsPersonsJoinMode.CUSTOM}
                />
            </div>

            <LemonButton type="primary" onClick={save} disabledReason={disabledReason}>
                Save
            </LemonButton>
        </div>
    )
}
