import { describe, expect, it } from "vitest";
import {
  extractPromptDisplayContent,
  makeAttachmentUri,
  parseAttachmentUri,
} from "./promptContent";

describe("promptContent", () => {
  it("builds unique attachment URIs for same-name files", () => {
    const firstUri = makeAttachmentUri("/tmp/one/README.md");
    const secondUri = makeAttachmentUri("/tmp/two/README.md");

    expect(firstUri).not.toBe(secondUri);
    expect(parseAttachmentUri(firstUri)).toEqual({
      id: firstUri,
      label: "README.md",
    });
    expect(parseAttachmentUri(secondUri)).toEqual({
      id: secondUri,
      label: "README.md",
    });
  });

  it("keeps duplicate file labels visible when attachment ids differ", () => {
    const firstUri = makeAttachmentUri("/tmp/one/README.md");
    const secondUri = makeAttachmentUri("/tmp/two/README.md");

    const result = extractPromptDisplayContent([
      { type: "text", text: "compare both" },
      {
        type: "resource",
        resource: { uri: firstUri, text: "first", mimeType: "text/markdown" },
      },
      {
        type: "resource",
        resource: {
          uri: secondUri,
          text: "second",
          mimeType: "text/markdown",
        },
      },
    ]);

    expect(result.text).toBe("compare both");
    expect(result.attachments).toEqual([
      { id: firstUri, label: "README.md" },
      { id: secondUri, label: "README.md" },
    ]);
  });

  it("extracts cloud resource_link attachments from file URIs", () => {
    const fileUri = "file:///tmp/workspace/attachments/Receipt-2264-0277.pdf";

    const result = extractPromptDisplayContent([
      { type: "text", text: "what is this about?" },
      {
        type: "resource_link",
        uri: fileUri,
        name: "Receipt-2264-0277.pdf",
      },
    ]);

    expect(result.text).toBe("what is this about?");
    expect(result.attachments).toEqual([
      { id: fileUri, label: "Receipt-2264-0277.pdf" },
    ]);
  });
});
