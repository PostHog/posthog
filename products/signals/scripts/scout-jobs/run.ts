import { parseArgs } from 'node:util'

import { createPostHogClient } from '@posthog/sdk'

import { ScoutJobs } from './jobs.ts'

const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
        'project-id': { type: 'string' },
        skill: { type: 'string' },
        memory: { type: 'string' },
        'run-id': { type: 'string' },
        from: { type: 'string' },
        to: { type: 'string' },
        hours: { type: 'string' },
        limit: { type: 'string' },
        'max-pages': { type: 'string' },
        'report-id': { type: 'string', multiple: true },
    },
})

const job = positionals[0]
if (positionals.length !== 1 || !['context', 'audit', 'errors', 'followups'].includes(job)) {
    throw new Error('Usage: node run.ts <context|audit|errors|followups> [--project-id ID] [job options]')
}
const projectId = values['project-id'] ? Number(values['project-id']) : undefined
if (projectId !== undefined && (!Number.isInteger(projectId) || projectId < 1)) {
    throw new Error('project-id must be a positive integer')
}
const jobs = new ScoutJobs(createPostHogClient({ projectId }))
const limit = values.limit === undefined ? undefined : Number(values.limit)
const to = values.to ?? new Date().toISOString()
const result =
    job === 'context'
        ? await jobs.context({
              skillName: values.skill ?? '',
              memoryText: values.memory,
              runId: values['run-id'],
              limit,
          })
        : job === 'audit'
          ? await jobs.audit({
                from: values.from ?? new Date(Date.parse(to) - 7 * 86400000).toISOString(),
                to,
                maxPages: values['max-pages'] === undefined ? undefined : Number(values['max-pages']),
            })
          : job === 'errors'
            ? await jobs.errors({ to, hours: values.hours === undefined ? undefined : Number(values.hours), limit })
            : await jobs.followups({ reportIds: values['report-id'], limit })
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
if (result.status === 'partial') {
    process.exitCode = 2
}
