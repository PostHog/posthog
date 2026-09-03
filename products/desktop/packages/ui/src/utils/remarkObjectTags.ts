import { unescapeXmlAttr } from "@posthog/shared";
import type { Parent, PhrasingContent, Root, RootContent } from "mdast";
import { CHART_BLOCK_MARKER } from "./chartBlocks";
import { resolveObjectKindName } from "./objectKinds";

/**
 * Remark plugin for the object tags agents embed in replies, the message-side
 * counterpart of the `<file path="..."/>` attachment convention:
 *
 *   <insight id="9pQx3">checkout funnel</insight>
 *   <flag id="42"/>
 *   <hogql label="errors today">SELECT count() FROM events ...</hogql>
 *   <insight id="9pQx3" display="block"/>
 *   <hogql display="block" title="DAU, last 7 days">SELECT ...</hogql>
 *
 * Tags normalize to the renderer's internal nodes, so the components stay
 * syntax-agnostic: inline tags become `evidence:<kind>/<id>` link nodes (the
 * reference chip), block tags become `posthog-chart` code nodes (the chart
 * card). Working on the AST keeps two guarantees for free: tags inside code
 * fences and inline code stay literal, and a half-streamed tag renders
 * nothing until the stream completes it (raw HTML nodes are not rendered).
 *
 * Only tags whose name resolves in the kind registry are touched; anything
 * else keeps react-markdown's default behavior.
 */

/**
 * Ceiling on block-display conversions per document. Every block card
 * executes an authenticated query on mount, so an unbounded tag count would
 * let one message fan out arbitrarily many concurrent queries; past the cap a
 * block tag degrades to an inline chip, which fetches only on hover.
 */
const MAX_BLOCK_TAGS = 10;

/** Mutable per-document budget threaded through the transform. */
interface TransformState {
  blockBudget: number;
}

const OPEN_TAG_RE = /^<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*>$/;
const COMPLETE_TAG_RE =
  /^<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*(?:\/>|>([\s\S]*?)<\/\1\s*>)$/;
const ATTR_RE = /([a-z][\w-]*)\s*=\s*"([^"]*)"/g;

interface ParsedTag {
  kind: string;
  attrs: Record<string, string>;
  /** Raw body text when the whole tag sat in one html node. */
  body?: string;
  /** Parsed label nodes when the open/close pair spanned siblings. */
  labelNodes?: PhrasingContent[];
}

function parseAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const match of raw.matchAll(ATTR_RE)) {
    attrs[match[1]] = unescapeXmlAttr(match[2]);
  }
  return attrs;
}

function matchCompleteTag(value: string): ParsedTag | null {
  const match = COMPLETE_TAG_RE.exec(value.trim());
  if (!match) return null;
  const kind = resolveObjectKindName(match[1]);
  if (!kind) return null;
  return { kind, attrs: parseAttrs(match[2]), body: match[3] };
}

function matchOpenTag(
  value: string,
): { tag: string; kind: string; attrs: Record<string, string> } | null {
  const match = OPEN_TAG_RE.exec(value.trim());
  if (!match) return null;
  const kind = resolveObjectKindName(match[1]);
  if (!kind) return null;
  return { tag: match[1], kind, attrs: parseAttrs(match[2]) };
}

function text(value: string): PhrasingContent {
  return { type: "text", value };
}

/** Plain text of the nodes between an open and close tag (SQL bodies). */
function nodesToText(nodes: PhrasingContent[]): string {
  return nodes
    .map((node) => {
      if ("value" in node && typeof node.value === "string") return node.value;
      if ("children" in node) {
        return nodesToText(node.children as PhrasingContent[]);
      }
      return "";
    })
    .join("");
}

function inlineNode(tag: ParsedTag): PhrasingContent | null {
  if (tag.kind === "hogql") {
    const query = (
      tag.body ?? (tag.labelNodes ? nodesToText(tag.labelNodes) : "")
    ).trim();
    if (!query) return null;
    return {
      type: "link",
      url: `evidence:hogql/${encodeURIComponent(query)}`,
      children: [text(tag.attrs.label?.trim() || "SQL query")],
    };
  }
  const id = tag.attrs.id?.trim();
  if (!id) return null;
  const label = tag.labelNodes?.length
    ? tag.labelNodes
    : [text(tag.body?.trim() || id)];
  return {
    type: "link",
    url: `evidence:${tag.kind}/${encodeURIComponent(id)}`,
    children: label,
  };
}

/** Serialized spec for the chart-card code node; parseChartBlock reads it. */
function blockNode(tag: ParsedTag): RootContent | null {
  const title = tag.attrs.title?.trim() || undefined;
  const caption = tag.attrs.caption?.trim() || undefined;
  let spec: Record<string, unknown> | null = null;
  if (tag.kind === "hogql") {
    const query = (
      tag.body ?? (tag.labelNodes ? nodesToText(tag.labelNodes) : "")
    ).trim();
    if (query) spec = { mode: "hogql", query, title, caption };
  } else if (tag.kind === "insight") {
    const shortId = tag.attrs.id?.trim();
    if (shortId) spec = { mode: "insight", shortId, title, caption };
  } else if (tag.kind === "replay") {
    const sessionId = tag.attrs.id?.trim();
    if (sessionId) spec = { mode: "replay", sessionId, title, caption };
  }
  if (!spec) return null;
  return {
    type: "code",
    lang: "posthog-chart",
    value: JSON.stringify(spec),
    // The marker is what lets the renderer trust this node: it can only be
    // set from the AST, never from markdown text, so a hand-authored
    // ```posthog-chart fence stays inert (see isGeneratedChartBlock).
    data: { hProperties: { [CHART_BLOCK_MARKER]: "true" } },
  };
}

function convert(
  tag: ParsedTag,
  inFlow: boolean,
  state: TransformState,
): RootContent | null {
  if (inFlow && tag.attrs.display === "block" && state.blockBudget > 0) {
    const block = blockNode(tag);
    if (block) {
      state.blockBudget--;
      return block;
    }
  }
  const inline = inlineNode(tag);
  if (!inline) return null;
  // A chip at block level needs a paragraph around it to flow as text.
  return inFlow
    ? ({ type: "paragraph", children: [inline] } as RootContent)
    : (inline as RootContent);
}

/** The node opens a known tag (streaming may not have completed it yet). */
function startsKnownTag(value: string): boolean {
  const match = /^<\/?([a-z][\w-]*)/.exec(value.trim());
  return match !== null && resolveObjectKindName(match[1]) !== null;
}

/**
 * Consume the html node at `index` (plus, for a spanning open/close pair, the
 * siblings up to the closing node). Returns null when it isn't an object tag;
 * returns zero nodes for a known tag the stream hasn't completed yet, so a
 * half-streamed tag shows nothing rather than raw markup.
 */
function consumeHtml(
  children: RootContent[],
  index: number,
  inFlow: boolean,
  state: TransformState,
): { nodes: RootContent[]; nextIndex: number } | null {
  const value = (children[index] as { value: string }).value;

  const complete = matchCompleteTag(value);
  if (complete) {
    const node = convert(complete, inFlow, state);
    return { nodes: node ? [node] : [], nextIndex: index + 1 };
  }

  const open = matchOpenTag(value);
  if (open) {
    for (let j = index + 1; j < children.length; j++) {
      const sibling = children[j];
      if (
        sibling.type === "html" &&
        sibling.value.trim() === `</${open.tag}>`
      ) {
        const label = children.slice(index + 1, j) as PhrasingContent[];
        const node = convert(
          { kind: open.kind, attrs: open.attrs, labelNodes: label },
          inFlow,
          state,
        );
        return { nodes: node ? [node] : [], nextIndex: j + 1 };
      }
    }
  }

  // Known tag, malformed or still streaming: hide the markup itself. Any
  // in-between label text keeps flowing until the closing tag arrives.
  if (startsKnownTag(value)) return { nodes: [], nextIndex: index + 1 };
  return null;
}

/**
 * A paragraph that is nothing but one block-display tag becomes the block
 * node itself. Markdown only forms an HTML *block* when the opening tag line
 * carries nothing else, so the common single-line form
 * `<hogql display="block">SELECT ...</hogql>` arrives as a paragraph of
 * inline html; without the lift it would downgrade to an inline chip.
 */
function liftParagraphBlockTag(
  paragraph: Parent,
  state: TransformState,
): RootContent | null {
  if (state.blockBudget <= 0) return null;
  const kids = paragraph.children as RootContent[];
  if (kids.length === 0) return null;

  let block: RootContent | null = null;
  if (kids.length === 1 && kids[0].type === "html") {
    const tag = matchCompleteTag(kids[0].value);
    block = tag && tag.attrs.display === "block" ? blockNode(tag) : null;
  } else {
    const first = kids[0];
    const last = kids[kids.length - 1];
    if (first.type !== "html" || last.type !== "html") return null;
    const open = matchOpenTag(first.value);
    if (
      !open ||
      open.attrs.display !== "block" ||
      last.value.trim() !== `</${open.tag}>`
    ) {
      return null;
    }
    block = blockNode({
      kind: open.kind,
      attrs: open.attrs,
      labelNodes: kids.slice(1, -1) as PhrasingContent[],
    });
  }
  if (block) state.blockBudget--;
  return block;
}

/**
 * MDAST containers whose children are block content, so a lifted chart code
 * node is valid inside them. Phrasing containers (paragraph, heading,
 * emphasis) are absent on purpose: a block tag nested in their inline flow
 * stays an inline chip rather than becoming an invalid nested block.
 */
const FLOW_CONTAINERS = new Set([
  "listItem",
  "blockquote",
  "footnoteDefinition",
]);

function transformChildren(
  parent: Parent,
  inFlow: boolean,
  state: TransformState,
): void {
  const out: RootContent[] = [];
  const children = parent.children as RootContent[];
  for (let i = 0; i < children.length; i++) {
    const child = children[i];
    if (child.type === "html") {
      const consumed = consumeHtml(children, i, inFlow, state);
      if (consumed) {
        out.push(...consumed.nodes);
        i = consumed.nextIndex - 1;
        continue;
      }
    }
    if (inFlow && child.type === "paragraph") {
      const lifted = liftParagraphBlockTag(child as Parent, state);
      if (lifted) {
        out.push(lifted);
        continue;
      }
    }
    if ("children" in child) {
      transformChildren(
        child as Parent,
        FLOW_CONTAINERS.has(child.type),
        state,
      );
    }
    out.push(child);
  }
  parent.children = out as Parent["children"];
}

export function remarkObjectTags() {
  return (tree: Root): void => {
    transformChildren(tree, true, { blockBudget: MAX_BLOCK_TAGS });
  };
}
