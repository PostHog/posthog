async function perform(action, args) {
    if (getState().busy) return
    setState({ busy: true, error: '' })
    try {
        if (action === 'connect') await host.call('tools', 'connect', {})
        if (action === 'call') setState({ result: await host.call('tools', 'call', args) })
        else setState({ servers: await host.call('tools', 'discover', {}) })
    } catch (e) {
        setState({ error: e.message })
    } finally {
        setState({ busy: false })
    }
}
view({
    state: { servers: [], busy: false, error: '', result: null },
    async init() {
        await perform('discover')
    },
    render(s) {
        const server = s.servers[0]
        return Page(
            Reading(
                { gap: 16 },
                Header(
                    { title: 'Tool servers', subtitle: 'Personal connections in the local project' },
                    IconButton('refresh-cw', {
                        label: 'Refresh servers',
                        disabled: s.busy,
                        onClick: () => perform('discover'),
                    })
                ),
                Scroll(
                    { gap: 16 },
                    Heading('Reading library', { size: 14 }),
                    !server && Caption('Connect this server to list your reading collections.'),
                    !server &&
                        Row(
                            Button('Connect server', {
                                id: 'connect-server',
                                variant: 'primary',
                                disabled: s.busy,
                                onClick: () => perform('connect'),
                            })
                        ),
                    server &&
                        server.tools.map((tool) =>
                            Column(
                                { gap: 8 },
                                Text(tool.description),
                                Caption(tool.name),
                                tool.approval === 'approved'
                                    ? Row(
                                          Button('Run tool', {
                                              id: 'run-' + tool.name,
                                              disabled: s.busy,
                                              onClick: () => perform('call', { id: server.id, name: tool.name }),
                                          })
                                      )
                                    : Caption('Approval required')
                            )
                        ),
                    s.result &&
                        Column({ gap: 6 }, Caption('Collections'), ...s.result.collections.map((name) => Text(name))),
                    s.error && ErrorMessage(s.error)
                )
            )
        )
    },
    inspect: (s) => ({ servers: s.servers, result: s.result, busy: s.busy, error: s.error }),
})
