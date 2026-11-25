; PHP injection rules
; Based on tree-sitter-php injections.scm with added HTML support for text nodes

((comment) @injection.content
  (#set! injection.language "phpdoc"))

(heredoc
  (heredoc_body) @injection.content
  (heredoc_end) @injection.language)

(nowdoc
  (nowdoc_body) @injection.content
  (heredoc_end) @injection.language)

; HTML in text nodes (content outside <?php ?> tags)
; injection.combined tells the highlighter to merge all text nodes into a single
; HTML document before parsing, so opening/closing tags across PHP blocks match.
((text) @injection.content
 (#set! injection.language "html")
 (#set! injection.combined))
