import type { InjectedBlock } from "@posthog/core/editor/injectedBlocks";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { INJECTED_BLOCK_PRESENTATION } from "@posthog/ui/features/sessions/components/session-update/injectedBlocks";

interface InjectedBlockTabProps {
  block: InjectedBlock;
}

export function InjectedBlockTab({ block }: InjectedBlockTabProps) {
  const { label, tab } = INJECTED_BLOCK_PRESENTATION[block.kind];
  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4">
        <p className="mb-3 text-[12px] text-gray-9">
          {tab?.intro(block) ?? label(block)}
        </p>
        {tab?.format === "markdown" ? (
          <div className="text-[13px]">
            <MarkdownRenderer content={block.body} />
          </div>
        ) : (
          <pre className="whitespace-pre-wrap break-words rounded-md border border-gray-6 bg-gray-2 p-3 font-mono text-[12px] text-gray-11">
            {block.body}
          </pre>
        )}
      </div>
    </div>
  );
}
