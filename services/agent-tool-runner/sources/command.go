// source `command` — runs a templated shell command and returns stdout as
// the tool result. The template is split into space-delimited tokens at
// construction; at call time, `${args.X}` placeholders inside each token
// are substituted with values from the invocation args.
//
// Security model:
//   - **No shell is invoked.** We use exec.CommandContext with an explicit
//     arg slice, never `bash -c`. Substituted values cannot escape their
//     token to inject additional arguments or shell metacharacters.
//   - Inputs are validated against the configured JSON Schema before
//     substitution. Required fields, types, and (e.g.) regex patterns
//     all enforced before the command runs.
//   - Substituted values become exactly one argv entry each, regardless
//     of their content (spaces, quotes, semicolons all safe).
//
// Output:
//   - On exit code 0: stdout is captured and returned as a JSON string.
//   - On non-zero exit: the error carries the exit code + first 1 KiB of
//     stderr. Stdout is discarded.
//
// What's NOT supported (intentional — keep the surface small):
//   - stdin to the command. No tool needs it for v1.
//   - Streaming output. Stdout is captured fully before returning.
//   - Environment variable templating. Use SecretsEnvs for credentials.
package sources

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"regexp"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/posthog/posthog/services/agent-tool-runner/protocol"
)

// CommandSpec describes one shell-command tool the source exposes.
type CommandSpec struct {
	// Qualified name as it will appear in the catalog
	// (e.g. "kubernetes.restart_deployment"). The runner enforces uniqueness.
	Name string

	// Free-text description shown to the agent (and surfaced in the
	// PostHog UI when previewing the catalog).
	Description string

	// JSON Schema (as a Go map, parsed from YAML) for the arg object.
	// Stored raw so the source compiles its own validator + the runner
	// publishes the schema verbatim to PostHog.
	ArgsSchema map[string]any

	// Template, e.g. `kubectl rollout restart deployment/${args.name}`.
	Command string
}

// CommandSource holds one or more CommandSpecs.
type CommandSource struct {
	specs    []CommandSpec
	compiled map[string]*compiledCommand
}

type compiledCommand struct {
	spec        CommandSpec
	tokens      []string           // raw tokens (each may contain placeholders)
	schema      *jsonschema.Schema // nil if no schema configured
	inputSchema json.RawMessage    // marshalled schema for the catalog
}

// NewCommandSource validates the spec list, compiles each command template,
// and pre-compiles each tool's JSON Schema validator.
func NewCommandSource(specs []CommandSpec) (*CommandSource, error) {
	compiled := make(map[string]*compiledCommand, len(specs))
	for i, spec := range specs {
		if spec.Name == "" {
			return nil, fmt.Errorf("command source: specs[%d]: name is required", i)
		}
		if spec.Command == "" {
			return nil, fmt.Errorf("command source: specs[%d]: command template is required", i)
		}
		if _, dup := compiled[spec.Name]; dup {
			return nil, fmt.Errorf("command source: duplicate tool name %q", spec.Name)
		}
		c, err := compile(spec)
		if err != nil {
			return nil, fmt.Errorf("command source %q: %w", spec.Name, err)
		}
		compiled[spec.Name] = c
	}
	return &CommandSource{specs: specs, compiled: compiled}, nil
}

func compile(spec CommandSpec) (*compiledCommand, error) {
	tokens := strings.Fields(spec.Command)
	if len(tokens) == 0 {
		return nil, errors.New("command template is empty")
	}

	c := &compiledCommand{spec: spec, tokens: tokens}

	if spec.ArgsSchema != nil {
		schemaJSON, err := json.Marshal(spec.ArgsSchema)
		if err != nil {
			return nil, fmt.Errorf("marshal args_schema: %w", err)
		}
		c.inputSchema = schemaJSON

		compiler := jsonschema.NewCompiler()
		var parsed any
		if err := json.Unmarshal(schemaJSON, &parsed); err != nil {
			return nil, fmt.Errorf("parse args_schema for validator: %w", err)
		}
		if err := compiler.AddResource("args.json", parsed); err != nil {
			return nil, fmt.Errorf("compile args_schema: %w", err)
		}
		schema, err := compiler.Compile("args.json")
		if err != nil {
			return nil, fmt.Errorf("compile args_schema: %w", err)
		}
		c.schema = schema
	} else {
		// No schema → publish an empty-object schema so the agent knows
		// it can pass nothing.
		c.inputSchema = json.RawMessage(`{"type":"object","properties":{}}`)
	}

	return c, nil
}

func (s *CommandSource) Tools() []protocol.ToolDescriptor {
	out := make([]protocol.ToolDescriptor, 0, len(s.specs))
	for _, spec := range s.specs {
		c := s.compiled[spec.Name]
		out = append(out, protocol.ToolDescriptor{
			Name:        spec.Name,
			Description: spec.Description,
			InputSchema: c.inputSchema,
		})
	}
	return out
}

// Close is a no-op for command sources — there's no persistent state.
// Implemented to satisfy the runner.Source interface.
func (s *CommandSource) Close() error { return nil }

// Call validates args against the schema, substitutes placeholders, execs
// the command under ctx, and returns stdout as a JSON-encoded string.
func (s *CommandSource) Call(ctx context.Context, toolName string, args json.RawMessage) (json.RawMessage, error) {
	c, ok := s.compiled[toolName]
	if !ok {
		return nil, fmt.Errorf("command source: unknown tool %q", toolName)
	}

	argMap, err := unmarshalArgs(args)
	if err != nil {
		return nil, fmt.Errorf("command source %q: %w", toolName, err)
	}
	if c.schema != nil {
		if err := c.schema.Validate(argMap); err != nil {
			return nil, fmt.Errorf("command source %q: args validation failed: %w", toolName, err)
		}
	}

	argv, err := substituteTokens(c.tokens, argMap)
	if err != nil {
		return nil, fmt.Errorf("command source %q: %w", toolName, err)
	}

	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		stderrTail := truncateForError(stderr.String(), 1024)
		return nil, fmt.Errorf(
			"command source %q: exec failed: %w (stderr: %s)",
			toolName, err, stderrTail,
		)
	}
	result, err := json.Marshal(stdout.String())
	if err != nil {
		return nil, fmt.Errorf("command source %q: marshal stdout: %w", toolName, err)
	}
	return result, nil
}

// placeholderRE matches `${args.<key>}` where <key> is a top-level JSON
// object property. Nested paths are not supported in v1 — flatten in the
// caller if you need them.
var placeholderRE = regexp.MustCompile(`\$\{args\.([a-zA-Z_][a-zA-Z0-9_]*)\}`)

func substituteTokens(tokens []string, args map[string]any) ([]string, error) {
	out := make([]string, len(tokens))
	for i, tok := range tokens {
		matches := placeholderRE.FindAllStringSubmatchIndex(tok, -1)
		if len(matches) == 0 {
			out[i] = tok
			continue
		}
		var b strings.Builder
		last := 0
		for _, m := range matches {
			b.WriteString(tok[last:m[0]])
			key := tok[m[2]:m[3]]
			value, ok := args[key]
			if !ok {
				return nil, fmt.Errorf("template references args.%s which is not provided", key)
			}
			b.WriteString(stringifyArg(value))
			last = m[1]
		}
		b.WriteString(tok[last:])
		out[i] = b.String()
	}
	return out, nil
}

// stringifyArg renders a JSON-decoded value as a string suitable for use
// as a single argv entry. Strings pass through verbatim; everything else
// goes through json.Marshal so booleans, numbers, and nested structures
// have a defined string form.
func stringifyArg(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	bytes, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprint(v) // last resort; should be unreachable for json-decoded values
	}
	return string(bytes)
}

func unmarshalArgs(raw json.RawMessage) (map[string]any, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return map[string]any{}, nil
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, fmt.Errorf("args must be a JSON object: %w", err)
	}
	return m, nil
}

func truncateForError(s string, n int) string {
	s = strings.TrimSpace(s)
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
