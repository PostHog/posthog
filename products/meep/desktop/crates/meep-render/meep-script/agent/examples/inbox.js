// A read-only GitHub pull request inbox through a permitted `gh pr list`
// action. Declared needs let the host ask once before loading.
const FIELDS = 'number,title,url,author,updatedAt,statusCheckRollup,reviewDecision'
view({
    needs: [{ cli: 'gh', action: ['pr', 'list'] }],
    state: { rows: [], selected: null, loading: false, error: null },
    async init() {
        await reload()
    },
    keys: { down: () => move(1), up: () => move(-1), enter: open },
    commands: {
        refresh() {
            return reload()
        },
        select({ index }) {
            setState({ selected: Number.isInteger(index) && index < getState().rows.length ? index : null })
        },
    },
    badge: (s) => ({
        value: s.rows.filter((r) => r.needsReview).length,
        title: s.rows.some((r) => r.needsReview) ? 'Pull requests waiting for your review' : 'You’re all caught up',
        items: s.rows
            .map((r, index) => ({ r, index }))
            .filter(({ r }) => r.needsReview)
            .slice(0, 5)
            .map(({ r, index }) => ({
                label: r.title || 'Untitled',
                detail: '#' + r.number + ' · ' + r.checks,
                command: 'select',
                args: { index },
            })),
    }),
    inspect: (s) => ({ rows: s.rows.length, selected: s.selected }),
    render(s) {
        const item = s.selected === null ? null : s.rows[s.selected]
        return Page(
            { align: 'center' },
            Reading(
                { gap: 0 },
                Header(
                    {
                        title: 'Pull requests',
                        subtitle: s.loading ? 'Refreshing…' : plural(s.rows.length, 'pull request'),
                    },
                    IconButton('refresh-cw', { label: 'Refresh', disabled: s.loading, onClick: reload })
                ),
                s.error ? ErrorMessage(s.error) : null,
                s.rows.length === 0
                    ? s.loading
                        ? Loading()
                        : Empty('You’re all caught up', 'Pull requests will appear here after the next refresh.')
                    : null,
                List({
                    id: 'pulls',
                    count: s.rows.length,
                    scrollTo: s.selected,
                    row: (i) => {
                        const r = s.rows[i]
                        return ListRow(
                            r.title || 'Untitled',
                            '#' + r.number + ' · ' + (r.author || 'Unknown author') + ' · ' + r.checks,
                            {
                                id: 'item-' + i,
                                selected: s.selected === i,
                                onClick: () => setState({ selected: i }),
                            }
                        )
                    },
                }),
                item
                    ? Column(
                          { gap: 10, pt: 20, border: 'top' },
                          Text(item.title || 'Untitled', { weight: 'medium' }),
                          item.url
                              ? Row(
                                    Button('Open in GitHub', { onClick: open }),
                                    Button('Copy link', { onClick: () => host.copy(item.url) })
                                )
                              : null
                      )
                    : null
            )
        )
    },
})

async function reload() {
    if (getState().loading) return
    setState({ loading: true, error: null })
    try {
        const result = await host.cli('gh', ['pr', 'list', '--json', FIELDS, '--limit', '100'])
        if (!result.success) throw new Error(result.stderr || 'GitHub did not return pull requests')
        const rows = (result.data || []).slice(0, 100).map((pr) => ({
            needsReview: pr.reviewDecision === 'REVIEW_REQUIRED',
            title: pr.title,
            number: pr.number,
            url: pr.url,
            author: pr.author && pr.author.login,
            checks: checks(pr.statusCheckRollup),
        }))
        setState((s) => ({
            rows,
            loading: false,
            selected: s.selected !== null && s.selected < rows.length ? s.selected : null,
        }))
    } catch (e) {
        setState({ loading: false, error: e.message })
    }
}
function checks(rollup) {
    if (!rollup || !rollup.length) return 'No checks'
    if (rollup.some((c) => ['FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED'].includes(c.conclusion)))
        return 'Checks failing'
    if (rollup.some((c) => c.status && c.status !== 'COMPLETED')) return 'Checks running'
    return 'Checks passed'
}
function move(delta) {
    const { rows, selected } = getState()
    if (!rows.length) return
    const from = selected === null ? (delta > 0 ? -1 : rows.length) : selected
    setState({ selected: Math.max(0, Math.min(rows.length - 1, from + delta)) })
}
function open() {
    const { rows, selected } = getState()
    const url = selected === null ? null : rows[selected] && rows[selected].url
    if (url && url.startsWith('https://')) host.openUrl(url)
}
function plural(n, word) {
    return n + ' ' + word + (n === 1 ? '' : 's')
}
