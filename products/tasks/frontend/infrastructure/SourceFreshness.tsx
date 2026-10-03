import { Badge, Card, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { Sources, fresh, sourceNames } from './infrastructureTypes'

const sourceLabels: Record<keyof Sources, string> = {
    package: 'Agent package',
    release: 'Release and version pin',
    base: 'Sandbox base',
    notebook: 'Notebook',
    streamlit: 'Streamlit',
    pi: 'Pi',
    autoresearch: 'Autoresearch',
    vm: 'VM base',
    custom: 'Custom images',
    dev_stack: 'PostHog dev stack',
}

export function SourceFreshness({ sources, now }: { sources: Sources; now: number }): JSX.Element {
    return (
        <Card className="sources-panel">
            <div className="section-title">
                <h2>Source freshness</h2>
                <p className="muted">Last successful reads, in UTC. Refresh to retry unavailable sources.</p>
            </div>
            <Table fullWidth tableClassName="table-fixed" aria-label="Source freshness">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-1/2">Source</TableHead>
                        <TableHead className="w-1/5">Status</TableHead>
                        <TableHead>Last read (UTC)</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {sourceNames.map((name) => {
                        const source = sources[name]
                        const isFresh = fresh(source, now)
                        return (
                            <TableRow key={name}>
                                <TableCell className="font-medium">{sourceLabels[name]}</TableCell>
                                <TableCell>
                                    <Badge
                                        variant={
                                            isFresh
                                                ? 'success'
                                                : source?.status === 'error'
                                                  ? 'destructive'
                                                  : source?.status === 'ok'
                                                    ? 'warning'
                                                    : 'default'
                                        }
                                    >
                                        {isFresh
                                            ? 'Fresh'
                                            : source?.status === 'error'
                                              ? 'Unavailable'
                                              : source?.status === 'ok'
                                                ? 'Stale'
                                                : source?.status === 'refreshing'
                                                  ? 'Refreshing'
                                                  : 'Loading'}
                                    </Badge>
                                </TableCell>
                                <TableCell className="text-muted-foreground tabular-nums">
                                    {source?.observed_at ? (
                                        <time dateTime={source.observed_at} title={source.observed_at}>
                                            {dayjs(source.observed_at).utc().format('YYYY-MM-DD HH:mm:ss')}
                                        </time>
                                    ) : (
                                        'Not observed'
                                    )}
                                </TableCell>
                            </TableRow>
                        )
                    })}
                </TableBody>
            </Table>
        </Card>
    )
}
