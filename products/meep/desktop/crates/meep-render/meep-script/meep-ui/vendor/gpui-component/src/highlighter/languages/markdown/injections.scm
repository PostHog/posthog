(fenced_code_block
  (info_string
    (language) @injection.language)
  (code_fence_content) @injection.content)

((html_block) @injection.content (#set! injection.language "html"))

(document . (section . (thematic_break) (_) @injection.content (thematic_break)) (#set! injection.language "yaml"))

((minus_metadata) @injection.content (#set! injection.language "yaml"))

((plus_metadata) @injection.content (#set! injection.language "toml"))

((inline) @injection.content
  (#set! injection.language "markdown_inline")
  (#set! injection.combined))
