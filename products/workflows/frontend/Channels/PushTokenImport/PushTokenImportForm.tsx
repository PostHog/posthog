import { useActions, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { cn } from 'lib/utils/css-classes'

import { pushTokenImportLogic } from './pushTokenImportLogic'

const EXAMPLE_CSV = 'distinct_id,device_token\nuser-123,9f2c1a…\nuser-456,dGVzdC1mY20…'

/** Picks the CSV file of devices to upload. */
export function PushTokenImportForm(): JSX.Element {
    const { file, error } = useValues(pushTokenImportLogic)
    const { setFile } = useActions(pushTokenImportLogic)

    return (
        <>
            <span className="text-sm text-secondary">
                Upload a CSV file of devices, for example an export from your previous push provider. The first line
                must name the columns, and the file needs a <code>distinct_id</code> column with the ID your app passes
                to identify, and a <code>device_token</code> column with the APNs device token or FCM registration
                token. Add one line per device. Other columns are ignored.
            </span>
            <pre className="text-xs bg-surface-secondary rounded p-2 m-0">{EXAMPLE_CSV}</pre>
            <LemonFileInput
                accept=".csv,text/csv"
                multiple={false}
                value={file ? [file] : []}
                onChange={(files) => setFile(files[0] ?? null)}
                showUploadedFiles={false}
                callToAction={
                    <div
                        className={cn(
                            'flex flex-col items-center justify-center flex-1 gap-1 p-8 border border-dashed border-primary hover:border-secondary',
                            file && 'border-success'
                        )}
                    >
                        <IconUpload className="text-5xl text-primary" />
                        <div>{file ? file.name : 'Drag a CSV file here or click to choose one'}</div>
                    </div>
                }
            />
            {error ? <LemonBanner type="error">{error}</LemonBanner> : null}
            <span className="text-xs text-secondary">
                PostHog imports the file in the background, so you can close this window once the upload is done. A
                distinct ID that no person in PostHog has is not imported, and the result lets you create those persons.
                Each device is saved with one event, so it counts toward your event usage.
            </span>
        </>
    )
}
