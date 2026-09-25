import type { ElementCommentAnchor } from "@posthog/core/comments/anchors";
import { describe, expect, it } from "vitest";
import { previewCommentComposerContent } from "./previewAgentContent";

const anchor: ElementCommentAnchor = {
  kind: "element",
  path: "/settings?tab=billing",
  selector: 'button[data-attr="save"]',
  tag: "button",
  text: "Save",
  html: '<button data-attr="save">Save</button>',
  attributes: { "data-attr": "save" },
};

describe("previewCommentComposerContent", () => {
  it.each([
    { name: "an empty draft", currentDraft: null, prefix: "" },
    {
      name: "a draft with text",
      currentDraft: "Fix the header",
      prefix: "\n\n",
    },
  ])(
    "gives the agent the element context after $name",
    ({ currentDraft, prefix }) => {
      const content = previewCommentComposerContent({
        port: 5173,
        anchor,
        comment: "@agent make this button   red",
        currentDraft,
      });

      expect(content.segments).toEqual([
        {
          type: "text",
          text: `${prefix}On the preview page http://localhost:5173/settings?tab=billing, change the <button> element "Save" at selector \`button[data-attr="save"]\`:\nmake this button red\n\nElement HTML:\n\`\`\`html\n<button data-attr="save">Save</button>\n\`\`\``,
        },
      ]);
    },
  );
});
