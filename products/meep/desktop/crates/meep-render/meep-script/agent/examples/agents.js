// Three independent uses of the same agent service. Nothing invokes a model
// until the person submits work. Replace the sample notes with real view data.
let observe
view({
    state: {
        tab: 0,
        notes: 'API migration is ready. Design review is on Friday.',
        summary: '',
        job: null,
        activity: '',
        session: null,
        profiles: [],
        selection: {},
        error: null,
    },
    async init() {
        setState({ profiles: await host.agents.catalog() })
        const s = getState()
        if (s.session) await host.agents.bind(s.session)
        if (s.job) await watchJob(s.job)
    },
    commands: { summarize, startDigest, openConversation },
    render(s) {
        return Page(
            { gap: 16 },
            Header({ title: 'Agent toolkit' }),
            Tabs({
                id: 'agent-mode',
                items: ['Result only', 'Background + events', 'Optional chat'],
                selected: s.tab,
                onChange: (tab) => setState({ tab }),
            }),
            s.error ? ErrorMessage(s.error) : null,
            s.tab < 2
                ? Column(
                      { gap: 12 },
                      AgentPicker({
                          id: 'task-agent',
                          profiles: s.profiles,
                          selection: s.selection,
                          onChange: (selection) => setState({ selection }),
                      }),
                      Textarea({
                          id: 'notes',
                          label: 'Notes',
                          value: s.notes,
                          rows: 5,
                          onChange: (notes) => setState({ notes }),
                      }),
                      Button(s.tab === 0 ? 'Summarize' : 'Start background digest', {
                          variant: 'primary',
                          onClick: s.tab === 0 ? summarize : startDigest,
                      }),
                      s.activity ? Caption(s.activity) : null,
                      s.job ? Button('Stop job', { onClick: () => host.agents.cancel(s.job) }) : null,
                      s.summary ? Markdown(s.summary, { id: 'summary', selectable: true }) : null
                  )
                : s.session
                  ? Chat({
                        id: 'conversation',
                        session: s.session,
                        onSessionChange: (session) => setState({ session }),
                    })
                  : Button('Open conversation', { onClick: openConversation })
        )
    },
})
async function access(capability) {
    const permissions = await host.permissions()
    if ((permissions.access.native || []).includes(capability)) return true
    return host.request({
        kind: 'native',
        capability,
        allowed: true,
        reason:
            capability === 'agents'
                ? 'Use your agent for these notes.'
                : 'Let the digest finish while this view is closed.',
    })
}
async function summarize() {
    try {
        if (!(await access('agents'))) return
        setState({ error: null, activity: 'Summarizing…' })
        const run = await host.agents.start({
            prompt: 'Summarize these notes in three short bullets.',
            input: getState().notes,
            selection: getState().selection,
        })
        const result = await host.agents.result(run.id)
        setState({ summary: result.output, activity: 'Finished' })
    } catch (e) {
        setState({ error: e.message, activity: '' })
    }
}
async function startDigest() {
    try {
        if (!(await access('agents')) || !(await access('background'))) return
        const run = await host.agents.start({
            prompt: 'Write a brief digest and propose the next action.',
            input: getState().notes,
            selection: getState().selection,
            execution: 'background',
        })
        setState({ job: run.id, summary: '', error: null })
        await watchJob(run.id)
    } catch (e) {
        setState({ error: e.message })
    }
}
async function watchJob(id) {
    if (observe) observe()
    observe = await host.agents.subscribe(
        id,
        async (event) => {
            if (event.type === 'error') {
                setState({ error: event.value })
                return
            }
            const run = event.type === 'snapshot' ? event.value : await host.agents.status(id)
            setState({ activity: run.status })
            if (run.status === 'completed') setState({ summary: run.output, job: null })
            else if (['error', 'cancelled', 'interrupted'].includes(run.status))
                setState({ error: run.error, job: null })
        },
        { events: ['status'] }
    )
}
async function openConversation() {
    try {
        const session = await host.agents.open({
            key: 'notes',
            instructions: "Help with the person's notes.",
            selection: getState().selection,
        })
        await host.agents.bind(session.id)
        setState({ session: session.id, error: null })
    } catch (e) {
        setState({ error: e.message })
    }
}
