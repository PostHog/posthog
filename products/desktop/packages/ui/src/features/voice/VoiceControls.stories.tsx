import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { VoiceControls } from "./VoiceControls";

const meta = {
  title: "Sessions/Voice controls",
  component: VoiceControls,
  args: { state: "idle", onStart: () => {}, onStop: () => {} },
} satisfies Meta<typeof VoiceControls>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Idle: Story = {};
export const Connecting: Story = { args: { state: "connecting" } };
export const Connected: Story = { args: { state: "connected" } };
export const YouSpeaking: Story = {
  args: { state: "connected", levels: { input: 0.25, output: 0 } },
};
export const AgentSpeaking: Story = {
  args: { state: "connected", levels: { input: 0, output: 0.25 } },
};
export const Closing: Story = { args: { state: "closing" } };
export const ConnectionError: Story = { args: { state: "error" } };
export const MicrophoneError: Story = { args: { state: "microphone-error" } };
export const ServiceError: Story = { args: { state: "service-error" } };
export const Disabled: Story = { args: { disabled: true } };

export const Composer: Story = {
  render: (args) => (
    <div className="flex w-full max-w-3xl flex-col gap-2">
      <PromptInput
        submitAdornment={<VoiceControls {...args} />}
        sessionId="voice-preview"
        placeholder="Type a message..."
        hideDefaultToolbar
        enableCommands={false}
        onSubmit={() => {}}
      />
    </div>
  ),
};
export const ComposerBefore: Story = {
  render: () => (
    <div className="w-full max-w-3xl">
      <PromptInput
        sessionId="voice-preview-before"
        placeholder="Type a message..."
        hideDefaultToolbar
        enableCommands={false}
        onSubmit={() => {}}
      />
    </div>
  ),
};
