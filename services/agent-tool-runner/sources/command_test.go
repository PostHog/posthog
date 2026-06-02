package sources

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func TestNewCommandSource_Validation(t *testing.T) {
	cases := []struct {
		name string
		spec CommandSpec
		want string
	}{
		{"no name", CommandSpec{Command: "echo"}, "name is required"},
		{"no command", CommandSpec{Name: "x.y"}, "command template is required"},
		{"empty template", CommandSpec{Name: "x.y", Command: "   "}, "command template is empty"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := NewCommandSource([]CommandSpec{tc.spec})
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Errorf("expected %q in error, got %v", tc.want, err)
			}
		})
	}
}

func TestNewCommandSource_DuplicateName(t *testing.T) {
	_, err := NewCommandSource([]CommandSpec{
		{Name: "k.r", Command: "echo a"},
		{Name: "k.r", Command: "echo b"},
	})
	if err == nil || !strings.Contains(err.Error(), "duplicate tool name") {
		t.Fatalf("expected duplicate error, got %v", err)
	}
}

func TestCall_PlainEcho(t *testing.T) {
	s, err := NewCommandSource([]CommandSpec{{
		Name:    "echo.hello",
		Command: "echo hello world",
	}})
	if err != nil {
		t.Fatalf("NewCommandSource: %v", err)
	}
	out, err := s.Call(context.Background(), "echo.hello", nil)
	if err != nil {
		t.Fatalf("Call: %v", err)
	}
	var got string
	if err := json.Unmarshal(out, &got); err != nil {
		t.Fatalf("decode result: %v", err)
	}
	if strings.TrimSpace(got) != "hello world" {
		t.Errorf("unexpected stdout: %q", got)
	}
}

func TestCall_SubstitutesArgs(t *testing.T) {
	s, err := NewCommandSource([]CommandSpec{{
		Name:    "echo.named",
		Command: "echo --name=${args.name}",
	}})
	if err != nil {
		t.Fatalf("NewCommandSource: %v", err)
	}
	out, err := s.Call(context.Background(), "echo.named", json.RawMessage(`{"name":"ben"}`))
	if err != nil {
		t.Fatalf("Call: %v", err)
	}
	var got string
	json.Unmarshal(out, &got)
	if strings.TrimSpace(got) != "--name=ben" {
		t.Errorf("unexpected stdout: %q", got)
	}
}

// Critical: substituted values must NOT be re-tokenized. A value with
// spaces stays one argv entry.
func TestCall_SubstitutedValueIsSingleArg(t *testing.T) {
	s, err := NewCommandSource([]CommandSpec{{
		Name:    "echo.single",
		Command: "echo ${args.msg}",
	}})
	if err != nil {
		t.Fatalf("NewCommandSource: %v", err)
	}
	out, err := s.Call(context.Background(), "echo.single", json.RawMessage(`{"msg":"one two three"}`))
	if err != nil {
		t.Fatalf("Call: %v", err)
	}
	var got string
	json.Unmarshal(out, &got)
	if strings.TrimSpace(got) != "one two three" {
		t.Errorf("unexpected stdout: %q", got)
	}
}

// Critical: shell metacharacters in a substituted value must be inert.
// Without shell, `;` and `&&` are just bytes in an argv entry.
func TestCall_ShellMetacharactersAreInert(t *testing.T) {
	s, err := NewCommandSource([]CommandSpec{{
		Name:    "echo.inject",
		Command: "echo ${args.payload}",
	}})
	if err != nil {
		t.Fatalf("NewCommandSource: %v", err)
	}
	payload := `"; rm -rf /; echo "pwned`
	body, _ := json.Marshal(map[string]string{"payload": payload})
	out, err := s.Call(context.Background(), "echo.inject", body)
	if err != nil {
		t.Fatalf("Call: %v", err)
	}
	var got string
	json.Unmarshal(out, &got)
	if !strings.Contains(got, payload) {
		t.Errorf("payload should pass through verbatim; got %q", got)
	}
}

func TestCall_MissingArgReferencedByTemplate(t *testing.T) {
	s, err := NewCommandSource([]CommandSpec{{
		Name:    "echo.named",
		Command: "echo ${args.name}",
	}})
	if err != nil {
		t.Fatalf("NewCommandSource: %v", err)
	}
	_, err = s.Call(context.Background(), "echo.named", json.RawMessage(`{}`))
	if err == nil || !strings.Contains(err.Error(), "args.name") {
		t.Errorf("expected error mentioning args.name, got %v", err)
	}
}

func TestCall_ArgsSchemaValidation(t *testing.T) {
	schema := map[string]any{
		"type":     "object",
		"required": []any{"name"},
		"properties": map[string]any{
			"name": map[string]any{"type": "string", "pattern": "^[a-z]+$"},
		},
	}
	s, err := NewCommandSource([]CommandSpec{{
		Name:       "echo.strict",
		Command:    "echo ${args.name}",
		ArgsSchema: schema,
	}})
	if err != nil {
		t.Fatalf("NewCommandSource: %v", err)
	}

	t.Run("valid", func(t *testing.T) {
		_, err := s.Call(context.Background(), "echo.strict", json.RawMessage(`{"name":"ben"}`))
		if err != nil {
			t.Errorf("expected valid args to pass: %v", err)
		}
	})
	t.Run("missing required", func(t *testing.T) {
		_, err := s.Call(context.Background(), "echo.strict", json.RawMessage(`{}`))
		if err == nil || !strings.Contains(err.Error(), "validation failed") {
			t.Errorf("expected validation failure, got %v", err)
		}
	})
	t.Run("pattern mismatch", func(t *testing.T) {
		_, err := s.Call(context.Background(), "echo.strict", json.RawMessage(`{"name":"Ben123"}`))
		if err == nil || !strings.Contains(err.Error(), "validation failed") {
			t.Errorf("expected validation failure, got %v", err)
		}
	})
}

func TestCall_NonZeroExitSurfacesStderr(t *testing.T) {
	s, err := NewCommandSource([]CommandSpec{{
		Name: "fail.hello",
		// `false` exits non-zero with no output. We capture its exit
		// status as an error.
		Command: "false",
	}})
	if err != nil {
		t.Fatalf("NewCommandSource: %v", err)
	}
	_, err = s.Call(context.Background(), "fail.hello", nil)
	if err == nil || !strings.Contains(err.Error(), "exec failed") {
		t.Errorf("expected exec failure, got %v", err)
	}
}

func TestCall_UnknownTool(t *testing.T) {
	s, err := NewCommandSource([]CommandSpec{{Name: "echo.hello", Command: "echo hi"}})
	if err != nil {
		t.Fatalf("NewCommandSource: %v", err)
	}
	_, err = s.Call(context.Background(), "echo.missing", nil)
	if err == nil || !strings.Contains(err.Error(), "unknown tool") {
		t.Errorf("expected unknown-tool error, got %v", err)
	}
}

func TestTools_PublishesCatalog(t *testing.T) {
	schema := map[string]any{"type": "object", "properties": map[string]any{}}
	s, _ := NewCommandSource([]CommandSpec{{
		Name:        "kubernetes.restart",
		Description: "restart a deployment",
		Command:     "true",
		ArgsSchema:  schema,
	}})
	tools := s.Tools()
	if len(tools) != 1 || tools[0].Name != "kubernetes.restart" || tools[0].Description != "restart a deployment" {
		t.Errorf("unexpected catalog: %+v", tools)
	}
	if len(tools[0].InputSchema) == 0 {
		t.Errorf("InputSchema should be populated")
	}
}

func TestSubstituteTokens_NonStringValue(t *testing.T) {
	tokens := []string{"--count", "${args.n}"}
	out, err := substituteTokens(tokens, map[string]any{"n": float64(42)})
	if err != nil {
		t.Fatalf("substituteTokens: %v", err)
	}
	if out[1] != "42" {
		t.Errorf("numeric arg should stringify; got %q", out[1])
	}
}
