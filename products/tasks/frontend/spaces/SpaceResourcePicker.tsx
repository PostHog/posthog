import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogBody,
    Input,
    Text,
} from '@posthog/quill'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { spaceResourcesLogic } from './spaceResourcesLogic'

export function SpaceResourcePicker({ id }: { id: string }): JSX.Element {
    const { pickerOpen, query, availableFiles, configLoading, filesLoading, filesUnavailable } = useValues(
        spaceResourcesLogic({ id })
    )
    const { setPickerOpen, setQuery, addFile, loadFiles } = useActions(spaceResourcesLogic({ id }))
    return (
        <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Add to space</DialogTitle>
                    <DialogDescription>
                        Choose an existing dashboard, insight, notebook, or folder. Its access permissions stay the
                        same.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-4">
                    <Input
                        aria-label="Search files to add"
                        placeholder="Search dashboards, insights, and folders…"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                    />
                    <div className="flex max-h-80 flex-col gap-1 overflow-y-auto">
                        {filesLoading ? (
                            <Text variant="muted">Loading files…</Text>
                        ) : filesUnavailable ? (
                            <Button onClick={() => loadFiles()}>Try loading files again</Button>
                        ) : availableFiles.length === 0 ? (
                            <Text variant="muted">No files match. Create a dashboard or try another search.</Text>
                        ) : (
                            availableFiles.slice(0, 100).map((file) => (
                                <Button
                                    key={file.id}
                                    variant="default"
                                    className="justify-start"
                                    loading={configLoading}
                                    onClick={() => addFile(file.id)}
                                    data-attr="space-add-resource"
                                >
                                    <span className="min-w-0 flex-1 truncate text-left">
                                        {splitPath(file.path).at(-1)}
                                    </span>
                                    <Text size="xs" variant="muted">
                                        {file.type}
                                    </Text>
                                </Button>
                            ))
                        )}
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
