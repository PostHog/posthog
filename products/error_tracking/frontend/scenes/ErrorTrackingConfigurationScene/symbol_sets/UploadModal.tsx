import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonFileInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconUploadFile } from 'lib/lemon-ui/icons'

import { symbolSetLogic } from './symbolSetLogic'

export const UploadModal = (): JSX.Element => {
    const { setUploadSymbolSetId } = useActions(symbolSetLogic)
    const { uploadSymbolSetId, isUploadSymbolSetSubmitting, uploadSymbolSet } = useValues(symbolSetLogic)

    const onClose = (): void => setUploadSymbolSetId(null)

    return (
        <LemonModal title="" onClose={onClose} isOpen={!!uploadSymbolSetId} simple>
            <Form logic={symbolSetLogic} formKey="uploadSymbolSet" className="gap-1" enableFormOnSubmit>
                <LemonModal.Header>
                    <h3>Upload javscript symbol set</h3>
                </LemonModal.Header>
                <LemonModal.Content className="deprecated-space-y-2">
                    <LemonField name="minified">
                        <LemonFileInput
                            accept="text/javascript"
                            multiple={false}
                            callToAction={
                                <div className="flex flex-col items-center justify-center deprecated-space-y-2 border border-dashed rounded p-4 w-full">
                                    <span className="flex items-center gap-2 font-semibold">
                                        <IconUploadFile className="text-2xl" /> Add minified source
                                    </span>
                                    <div>
                                        Drag and drop your minified source file here or click to open the file browser.
                                    </div>
                                </div>
                            }
                        />
                    </LemonField>
                    <LemonField name="sourceMap">
                        <LemonFileInput
                            accept="*"
                            multiple={false}
                            callToAction={
                                <div className="flex flex-col items-center justify-center deprecated-space-y-2 border border-dashed rounded p-4 w-full">
                                    <span className="flex items-center gap-2 font-semibold">
                                        <IconUploadFile className="text-2xl" /> Add source map
                                    </span>
                                    <div>Drag and drop your source map here or click to open the file browser.</div>
                                </div>
                            }
                        />
                    </LemonField>
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        disabledReason={
                            uploadSymbolSet.minified.length < 1
                                ? 'Upload a minified source'
                                : uploadSymbolSet.sourceMap.length < 1
                                  ? 'Upload a source map'
                                  : undefined
                        }
                        type="primary"
                        status="alt"
                        htmlType="submit"
                        loading={isUploadSymbolSetSubmitting}
                    >
                        Upload
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
