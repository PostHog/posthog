import { Properties } from '@posthog/plugin-scaffold'
import { nodePostHog } from 'posthog-js-lite/dist/src/targets/node'

import { DB } from '../../shared/db'
import { timeoutGuard } from '../../shared/ingestion/utils'
import { Team, TeamId } from '../../types'

type TeamWithEventUuid = Team & { __fetch_event_uuid?: string }

export class TeamManager {
    db: DB
    teamCache: Map<TeamId, [TeamWithEventUuid | null, number]>
    shouldSendWebhooksCache: Map<TeamId, [boolean, number]>

    constructor(db: DB) {
        this.db = db
        this.teamCache = new Map()
        this.shouldSendWebhooksCache = new Map()
    }

    public async fetchTeam(teamId: number, eventUuid?: string): Promise<Team | null> {
        const cachedTeam = this.getByAge(this.teamCache, teamId)
        if (cachedTeam) {
            return cachedTeam
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const teamQueryResult = await this.db.postgresQuery(
                'SELECT * FROM posthog_team WHERE id = $1',
                [teamId],
                'selectTeam'
            )
            const team: TeamWithEventUuid | null = teamQueryResult.rows[0] || null
            if (team) {
                team.__fetch_event_uuid = eventUuid
            }

            this.teamCache.set(teamId, [team, Date.now()])
            return team
        } finally {
            clearTimeout(timeout)
        }
    }

    public async shouldSendWebhooks(teamId: number): Promise<boolean> {
        const cachedValue = this.getByAge(this.shouldSendWebhooksCache, teamId)
        if (cachedValue !== undefined) {
            return cachedValue
        }

        const team = await this.fetchTeam(teamId)
        if (!team || !team.slack_incoming_webhook) {
            return false
        }

        const timeout = timeoutGuard(`Still running "shouldSendWebhooks". Timeout warning after 30 sec!`)
        try {
            const hookQueryResult = await this.db.postgresQuery(
                `SELECT COUNT(*) FROM ee_hook WHERE team_id = $1 AND event = 'action_performed' LIMIT 1`,
                [team.id],
                'shouldSendHooksTask'
            )
            const hasHooks = parseInt(hookQueryResult.rows[0].count) > 0
            this.shouldSendWebhooksCache.set(teamId, [hasHooks, Date.now()])
            return hasHooks
        } catch (error) {
            // In FOSS PostHog ee_hook does not exist. If the error is other than that, rethrow it
            if (!String(error).includes('relation "ee_hook" does not exist')) {
                throw error
            }
            return false
        } finally {
            clearTimeout(timeout)
        }
    }

    public async updateEventNamesAndProperties(
        teamId: number,
        event: string,
        eventUuid: string,
        properties: Properties,
        posthog: ReturnType<typeof nodePostHog>
    ): Promise<void> {
        let team: TeamWithEventUuid | null = await this.fetchTeam(teamId)

        if (!team) {
            return
        }

        const timeout = timeoutGuard('Still running "updateEventNamesAndProperties". Timeout warning after 30 sec!', {
            event: event,
            ingested: team.ingested_event,
        })
        let shouldUpdate = this.calculateUpdates(team, event, properties)
        if (shouldUpdate && team.__fetch_event_uuid !== eventUuid) {
            // :TRICKY: Double-check if we're updating based on cached data, if so, re-validate.
            // :TODO: Switch all of this to a sane schema that can be updated without races.
            this.teamCache.delete(teamId)
            team = await this.fetchTeam(teamId, eventUuid)
            shouldUpdate = this.calculateUpdates(team, event, properties)
        }
        if (team && shouldUpdate) {
            const timeout2 = timeoutGuard(
                'Still running "updateEventNamesAndProperties" save. Timeout warning after 30 sec!',
                { event }
            )
            await this.db.postgresQuery(
                `UPDATE posthog_team SET
                    ingested_event = $1,
                    event_names = $2,
                    event_names_with_usage = $3,
                    event_properties = $4,
                    event_properties_with_usage = $5,
                    event_properties_numerical = $6
                WHERE id = $7`,
                [
                    true,
                    JSON.stringify(team.event_names),
                    JSON.stringify(team.event_names_with_usage),
                    JSON.stringify(team.event_properties),
                    JSON.stringify(team.event_properties_with_usage),
                    JSON.stringify(team.event_properties_numerical),
                    team.id,
                ],
                'updateEventNamesAndProperties'
            )
            clearTimeout(timeout2)
        }
        if (team && !team.ingested_event) {
            // First event for the team captured
            const organizationMembers = await this.db.postgresQuery(
                'SELECT distinct_id FROM posthog_user JOIN posthog_organizationmembership ON posthog_user.id = posthog_organizationmembership.user_id WHERE organization_id = $1',
                [team.organization_id],
                'posthog_organizationmembership'
            )
            const distinctIds: { distinct_id: string }[] = organizationMembers.rows
            for (const { distinct_id } of distinctIds) {
                posthog.identify(distinct_id)
                posthog.capture('first team event ingested', { team: team.uuid })
            }
        }
        clearTimeout(timeout)
    }

    private calculateUpdates(team: Team | null, event: string, properties: Properties): boolean {
        if (!team) {
            return false
        }

        let shouldUpdate = false
        if (!team.ingested_event) {
            shouldUpdate = true
        }

        if (team.event_names && !team.event_names.includes(event)) {
            shouldUpdate = true
            team.event_names.push(event)
            team.event_names_with_usage.push({ event: event, usage_count: null, volume: null })
        }
        for (const [key, value] of Object.entries(properties)) {
            if (!team.event_properties || !team.event_properties.includes(key)) {
                team.event_properties.push(key)
                team.event_properties_with_usage.push({ key: key, usage_count: null, volume: null })
                shouldUpdate = true
            }
            if (
                typeof value === 'number' &&
                (!team.event_properties_numerical || !team.event_properties_numerical.includes(key))
            ) {
                team.event_properties_numerical.push(key)
                shouldUpdate = true
            }
        }

        return shouldUpdate
    }

    private getByAge<K, V>(cache: Map<K, [V, number]>, key: K, maxAgeMs = 30000): V | undefined {
        if (cache.has(key)) {
            const [value, age] = cache.get(key)!
            if (Date.now() - age <= maxAgeMs) {
                return value
            }
        }
        return undefined
    }
}
