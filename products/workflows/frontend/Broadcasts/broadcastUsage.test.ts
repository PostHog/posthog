import { advanceAgentDraft, broadcastPath, editedFields, saveComposerDraft, snapshotBroadcast } from './broadcastUsage'

function flow(overrides: { name?: string; subject?: string; html?: string; audience?: unknown[] }): any {
    return {
        name: overrides.name ?? 'Spring sale',
        conversion: null,
        actions: [
            { type: 'trigger', config: { filters: { properties: overrides.audience ?? [] } } },
            {
                type: 'function_email',
                config: {
                    inputs: {
                        email: {
                            value: {
                                from: { integrationId: 1 },
                                subject: overrides.subject ?? 'Our spring sale',
                                html: overrides.html ?? '<p>Hi</p>',
                            },
                        },
                    },
                },
            },
        ],
    }
}

describe('broadcastUsage', () => {
    it.each([
        {
            case: 'nothing changed',
            launched: flow({}),
            expected: [],
        },
        {
            case: 'the subject and audience changed',
            launched: flow({ subject: 'Our spring sale ends Friday', audience: [{ key: 'plan', value: 'pro' }] }),
            expected: ['audience', 'subject'],
        },
    ])('reports the edited fields when $case', ({ launched, expected }) => {
        expect(editedFields(snapshotBroadcast(flow({})), snapshotBroadcast(launched))).toEqual(expected)
    })

    it('keeps a saved edit of the person counted when the agent then edits another field', () => {
        const agentDraft = snapshotBroadcast(flow({}))
        // The person saved a new subject, then the agent rewrote the body. The copy the agent saved carries both.
        const base = snapshotBroadcast(flow({ subject: 'Last days of the sale' }))
        const latest = snapshotBroadcast(flow({ subject: 'Last days of the sale', html: '<p>Hi again</p>' }))

        const advanced = advanceAgentDraft(agentDraft, latest, base)

        expect(editedFields(advanced, latest)).toEqual(['subject'])
    })

    it('reports the composer path only for a draft the composer marked', () => {
        saveComposerDraft('broadcast-1', { agentDraft: snapshotBroadcast(flow({})), agentEdits: 0 })

        expect([broadcastPath('broadcast-1'), broadcastPath('broadcast-2'), broadcastPath(null)]).toEqual([
            'composer',
            'manual',
            'manual',
        ])
    })
})
