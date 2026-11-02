// Package hogqlparser runs the HogQL parser from rust/hogql/parser, compiled to WASM, so that the language service
// accepts exactly the grammar that query execution accepts.
package hogqlparser

import (
	"context"
	_ "embed"
	"errors"
	"fmt"
	"runtime"
	"sync"
	"unicode/utf8"

	"github.com/tetratelabs/wazero"
	"github.com/tetratelabs/wazero/api"
	"github.com/tetratelabs/wazero/imports/wasi_snapshot_preview1"
)

//go:generate ../../scripts/build-parser-wasm.sh

// hogql_parser.wasm is a build output, so it is not in version control. Run `go generate ./internal/hogqlparser`.
//
//go:embed hogql_parser.wasm
var wasmModule []byte

// An instance keeps the linear memory of its largest parse. Instances above this size are closed instead of
// returned to the pool, so that one large query does not hold its memory for the life of the process.
const maxPooledMemoryBytes = 64 << 20

// ErrInternal reports a parser failure that is not about the query, such as a WASM trap.
var ErrInternal = errors.New("internal HogQL parser error")

type SyntaxError struct {
	Type    string
	Message string
	// Start and End are byte offsets into the query.
	Start, End int
}

func (e *SyntaxError) Error() string {
	return e.Message
}

type engine struct {
	runtime  wazero.Runtime
	compiled wazero.CompiledModule
	idle     chan *instance
}

type instance struct {
	module api.Module
	alloc  api.Function
	free   api.Function
	parse  api.Function
}

var shared = sync.OnceValues(newEngine)

// Init compiles the WASM module. ParseSelect calls it on first use, and servers call it at startup so that the
// first request does not pay the compile time.
func Init() error {
	_, err := shared()
	return err
}

func newEngine() (*engine, error) {
	ctx := context.Background()
	wasmRuntime := wazero.NewRuntime(ctx)
	if _, err := wasi_snapshot_preview1.Instantiate(ctx, wasmRuntime); err != nil {
		return nil, fmt.Errorf("instantiate WASI: %w", err)
	}
	compiled, err := wasmRuntime.CompileModule(ctx, wasmModule)
	if err != nil {
		return nil, fmt.Errorf("compile HogQL parser: %w", err)
	}
	return &engine{runtime: wasmRuntime, compiled: compiled, idle: make(chan *instance, runtime.GOMAXPROCS(0))}, nil
}

func (e *engine) acquire(ctx context.Context) (*instance, error) {
	select {
	case idle := <-e.idle:
		return idle, nil
	default:
	}
	// An anonymous module can be instantiated many times, and Rust reactor modules export `_initialize`.
	module, err := e.runtime.InstantiateModule(ctx, e.compiled, wazero.NewModuleConfig().WithName("").WithStartFunctions("_initialize"))
	if err != nil {
		return nil, fmt.Errorf("instantiate HogQL parser: %w", err)
	}
	return &instance{
		module: module,
		alloc:  module.ExportedFunction("hogql_alloc"),
		free:   module.ExportedFunction("hogql_free"),
		parse:  module.ExportedFunction("hogql_parse_select"),
	}, nil
}

func (e *engine) release(ctx context.Context, used *instance) {
	if used.module.Memory().Size() > maxPooledMemoryBytes {
		_ = used.module.Close(ctx)
		return
	}
	select {
	case e.idle <- used:
	default:
		_ = used.module.Close(ctx)
	}
}

// A query that does not parse returns a *SyntaxError.
func ParseSelect(query string) (*Node, error) {
	output, err := parseSelectJSON(query)
	if err != nil {
		return nil, err
	}
	return decode(query, output)
}

func parseSelectJSON(query string) ([]byte, error) {
	parser, err := shared()
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrInternal, err)
	}
	ctx := context.Background()
	current, err := parser.acquire(ctx)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrInternal, err)
	}
	output, err := current.parseSelect(ctx, query)
	if err != nil {
		// A trap leaves the instance memory in an unknown state, so the instance must not be reused.
		_ = current.module.Close(ctx)
		return nil, fmt.Errorf("%w: %w", ErrInternal, err)
	}
	parser.release(ctx, current)
	return output, nil
}

func (i *instance) parseSelect(ctx context.Context, query string) ([]byte, error) {
	results, err := i.alloc.Call(ctx, uint64(len(query)))
	if err != nil {
		return nil, err
	}
	input := uint32(results[0])
	if !i.module.Memory().WriteString(input, query) {
		return nil, errors.New("query does not fit in parser memory")
	}
	results, err = i.parse.Call(ctx, uint64(input), uint64(len(query)))
	if err != nil {
		return nil, err
	}
	outputPointer, outputLength := uint32(results[0]>>32), uint32(results[0])
	view, ok := i.module.Memory().Read(outputPointer, outputLength)
	if !ok {
		return nil, errors.New("parser result is outside parser memory")
	}
	output := append([]byte(nil), view...)
	if _, err := i.free.Call(ctx, uint64(input), uint64(len(query))); err != nil {
		return nil, err
	}
	if _, err := i.free.Call(ctx, uint64(outputPointer), uint64(outputLength)); err != nil {
		return nil, err
	}
	return output, nil
}

// clampByteOffset keeps an offset inside the query and on a character boundary, because callers slice the query
// and convert offsets to UTF-16 with it.
func clampByteOffset(query string, offset int) int {
	offset = max(0, min(offset, len(query)))
	for offset > 0 && offset < len(query) && !utf8.RuneStart(query[offset]) {
		offset--
	}
	return offset
}
