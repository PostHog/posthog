// The SKILL.md serializer lives in @posthog/shared so the workspace-server
// bundler and the web-host bundler emit byte-identical SKILL.md files — this is
// a serialization contract the cloud sandbox consumes and must not drift.
export { serializeSkillMarkdown } from "@posthog/shared";
