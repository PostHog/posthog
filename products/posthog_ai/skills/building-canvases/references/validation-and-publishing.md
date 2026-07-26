# Validation and publishing

The source project contains:

```text
schemaVersion: 1
files: project-relative path to UTF-8 content
entryHtml: index.html
dependencies: package name to exact version
canvasSdkVersion: exact version
capabilities: PostHog and network declarations
```

Paths are normalized and project-relative. The project supports at most 128 files, 1 MB per file, and 5 MB total source.
The build admits only preinstalled browser packages, never runs dependency lifecycle scripts, rejects Node built-ins,
and produces immutable HTML, CSS, and JavaScript with a restrictive content security policy.

Validate the complete project with `canvas-source-validate`. Publishing stores a deterministic private source archive
and creates a separate authoritative cloud build. Never publish locally generated executable artifacts. The last
successful cloud artifact remains active until a newer current source version builds successfully.

When a build fails, inspect its bounded diagnostics, repair the source in a fresh run, and publish against the latest
version. Do not bypass dependency or capability checks to make a build pass.

Keep `capabilities.network.origins` empty. Direct external network access is disabled until a user-facing capability
approval flow exists; use the injected `ph` SDK for PostHog data and host-mediated actions.
