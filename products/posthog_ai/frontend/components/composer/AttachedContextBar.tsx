import { useThreadSkin } from '../../hooks/useThreadSkin'
import { QuillAttachedContextChips } from '../quill/QuillAttachedContextChips'
import { QuillAttachedContextPicker } from '../quill/QuillAttachedContextPicker'
import { AttachedContextChips } from './AttachedContextChips'
import { AttachedContextPicker } from './AttachedContextPicker'

export function AttachedContextBar(): JSX.Element | null {
    const skin = useThreadSkin()
    if (skin === 'quill') {
        return (
            <div className="flex min-w-0 flex-wrap items-center gap-1">
                <QuillAttachedContextPicker />
                <QuillAttachedContextChips />
            </div>
        )
    }
    return <AttachedContextChips leading={<AttachedContextPicker />} />
}
