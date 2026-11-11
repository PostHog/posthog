import { act, fireEvent, render } from '@testing-library/react-native'
import { Platform, Text, View } from 'react-native'
import { MermaidDiagram } from './MermaidDiagram'

jest.mock('react-native-webview', () => {
    const { View } = require('react-native')
    return { __esModule: true, default: (props: object) => <View testID="diagram-webview" {...props} /> }
})
jest.mock('mermaid/dist/mermaid.min.js', () => 'window.mermaid = {};')

it('keeps remote image diagrams as source without mounting a browser', () => {
    const screen = render(
        <MermaidDiagram
            code={'flowchart LR\n A@{ img: "https://example.com/image.png" }'}
            fallback={<Text>source fallback</Text>}
        />
    )
    expect(screen.getByText('source fallback')).toBeTruthy()
    expect(screen.queryByTestId('diagram-webview')).toBeNull()
})

it('sizes the diagram and refuses remote, file and script navigation', () => {
    const screen = render(<MermaidDiagram code={'flowchart LR\n A-->B'} fallback={<Text>source fallback</Text>} />)
    const frame = screen.UNSAFE_getAllByType(View).find((view) => view.props.onLayout)
    if (!frame) throw new Error('Missing diagram frame')
    fireEvent(frame, 'layout', { nativeEvent: { layout: { width: 320 } } })
    const browser = screen.getByTestId('diagram-webview')
    expect(browser.props.onShouldStartLoadWithRequest({ url: 'about:blank' })).toBe(true)
    for (const url of ['https://example.com', 'file:///etc/passwd', 'about:srcdoc', 'javascript:alert(1)']) {
        expect(browser.props.onShouldStartLoadWithRequest({ url })).toBe(false)
    }
    fireEvent(browser, 'message', { nativeEvent: { data: '{"type":"size","width":600,"height":180}' } })
    expect(screen.getByTestId('diagram-webview').props.style).toContainEqual({ width: 600, height: 180 })
    fireEvent(browser, 'message', { nativeEvent: { data: '{"type":"error"}' } })
    expect(screen.getByText('source fallback')).toBeTruthy()
})

it('falls back when the browser never finishes rendering', () => {
    jest.useFakeTimers()
    try {
        const screen = render(<MermaidDiagram code={'graph TD\n C-->D'} fallback={<Text>source fallback</Text>} />)
        act(() => jest.advanceTimersByTime(15000))
        expect(screen.getByText('source fallback')).toBeTruthy()
    } finally {
        jest.useRealTimers()
    }
})

it('shows source in web preview without invoking the native browser', () => {
    const previous = Platform.OS
    Object.defineProperty(Platform, 'OS', { value: 'web', configurable: true })
    try {
        const screen = render(<MermaidDiagram code="graph TD; A-->B" fallback={<Text>source fallback</Text>} />)
        expect(screen.getByText('source fallback')).toBeTruthy()
        expect(screen.queryByTestId('diagram-webview')).toBeNull()
    } finally {
        Object.defineProperty(Platform, 'OS', { value: previous, configurable: true })
    }
})
