package docker

import (
	"bufio"
	"context"
	"encoding/json"
	"image/color"
	"log"
	"os/exec"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/phrocs/internal/expand"
)

// Container represents a single docker compose service instance
type Container struct {
	Service string `json:"Service"`
	Name    string `json:"Name"`
	State   string `json:"State"`
	Health  string `json:"Health"`
}

// containersMsg is sent when container status is refreshed via polling
type containersMsg struct {
	Containers []Container
	err        error
	stderr     string
}

// logOutputMsg is sent when a container's log buffer receives a new line
type logOutputMsg struct {
	Service string
}

const pollInterval = 3 * time.Second

// ComposeFlags holds parsed -f and --profile flags from a docker compose command
type ComposeFlags struct {
	Files    []string
	Profiles []string
}

// PsArgs returns docker CLI arguments for `docker compose ps`
func (f ComposeFlags) PsArgs() []string {
	args := []string{"compose"}
	for _, file := range f.Files {
		args = append(args, "-f", file)
	}
	for _, profile := range f.Profiles {
		args = append(args, "--profile", profile)
	}
	args = append(args, "ps", "--format", "json")
	return args
}

// LogArgs returns docker CLI arguments for streaming a single service's logs
func (f ComposeFlags) LogArgs(service string) []string {
	args := []string{"compose"}
	for _, file := range f.Files {
		args = append(args, "-f", file)
	}
	for _, profile := range f.Profiles {
		args = append(args, "--profile", profile)
	}
	args = append(args, "logs", "--no-log-prefix", "--follow", "--tail", "100", service)
	return args
}

// logStream manages per-container log streaming via `docker compose logs`
type logStream struct {
	service  string
	mu       sync.Mutex
	lines    []string
	maxLines int
	cancel   context.CancelFunc
}

func newLogStream(service string, maxLines int) *logStream {
	return &logStream{
		service:  service,
		maxLines: maxLines,
	}
}

func (s *logStream) Lines() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := make([]string, len(s.lines))
	copy(cp, s.lines)
	return cp
}

func (s *logStream) appendLine(line string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.lines) >= s.maxLines {
		s.lines = s.lines[1:]
	}
	s.lines = append(s.lines, line)
}

func (s *logStream) stop() {
	if s.cancel != nil {
		s.cancel()
	}
}

func (s *logStream) start(flags ComposeFlags, send func(tea.Msg)) {
	ctx, cancel := context.WithCancel(context.Background())
	s.cancel = cancel

	args := flags.LogArgs(s.service)
	cmd := exec.CommandContext(ctx, "docker", args...)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		return
	}
	cmd.Stderr = cmd.Stdout // merge stderr into stdout

	if err := cmd.Start(); err != nil {
		cancel()
		return
	}

	go func() {
		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 256*1024), 256*1024)
		for scanner.Scan() {
			s.appendLine(scanner.Text())
			send(logOutputMsg{Service: s.service})
		}
		_ = cmd.Wait()
	}()
}

// ComposeExpander implements expand.Expander for docker compose services.
// It polls container status and streams per-service logs into individual buffers.
type ComposeExpander struct {
	procNames map[string]bool
	flags     ComposeFlags
	maxLines  int
	log       *log.Logger

	mu         sync.Mutex
	send       func(tea.Msg)
	containers []Container
	streams    map[string]*logStream
}

// NewComposeExpander creates a compose expander. It scans the given process
// shells to detect compose commands and extract their flags.
func NewComposeExpander(
	shells map[string]string, // procName → shell command
	maxLines int,
	logger *log.Logger,
) *ComposeExpander {
	e := &ComposeExpander{
		procNames: make(map[string]bool),
		maxLines:  maxLines,
		streams:   make(map[string]*logStream),
		log:       logger,
	}

	for name, shell := range shells {
		if !IsComposeCommand(shell) {
			continue
		}
		e.procNames[name] = true
		e.dbg("detected compose proc: %s", name)
		if len(e.flags.Files) == 0 {
			e.flags = ParseComposeFlags(shell)
			e.dbg("parsed flags: files=%v profiles=%v", e.flags.Files, e.flags.Profiles)
		}
	}

	return e
}

func (e *ComposeExpander) dbg(format string, args ...any) {
	if e.log != nil {
		e.log.Printf("[compose] "+format, args...)
	}
}

// HasComposeProcs reports whether any compose processes were detected
func (e *ComposeExpander) HasComposeProcs() bool {
	return len(e.procNames) > 0
}

// IsComposeProc reports whether the named process is a compose process
func (e *ComposeExpander) IsComposeProc(name string) bool {
	return e.procNames[name]
}

func (e *ComposeExpander) SetSend(send func(tea.Msg)) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.send = send
}

func (e *ComposeExpander) Init() tea.Cmd {
	if len(e.procNames) == 0 {
		return nil
	}
	return e.fetchCmd()
}

func (e *ComposeExpander) HandleMsg(msg tea.Msg) expand.Result {
	switch msg := msg.(type) {
	case containersMsg:
		cm := msg
		if cm.err != nil {
			e.dbg("poll error: %v stderr=%q", cm.err, cm.stderr)
		}
		e.dbg("poll: got %d containers", len(cm.Containers))
		for _, c := range cm.Containers {
			e.dbg("  container: service=%s state=%s health=%s", c.Service, c.State, c.Health)
		}
		e.mu.Lock()
		e.containers = cm.Containers
		send := e.send
		e.mu.Unlock()

		e.reconcileStreams(send)

		return expand.Result{
			RebuildRows:   true,
			RefreshOutput: true,
			Cmd:           e.pollCmd(),
		}

	case logOutputMsg:
		return expand.Result{RefreshOutput: true}
	}

	return expand.Result{}
}

func (e *ComposeExpander) ChildrenFor(procName string) []expand.Child {
	if !e.procNames[procName] {
		return nil
	}

	e.mu.Lock()
	containers := e.containers
	e.mu.Unlock()

	e.dbg("ChildrenFor(%s): %d containers", procName, len(containers))

	var children []expand.Child
	for _, c := range containers {
		stream := e.streams[c.Service]
		var output func() []string
		if stream != nil {
			s := stream // capture for closure
			output = s.Lines
		}

		children = append(children, expand.Child{
			Name:      c.Service,
			IconChar:  ContainerIconChar(c),
			IconColor: ContainerIconColor(c),
			Output:    output,
		})
	}
	return children
}

func (e *ComposeExpander) ParentIcon(procName string) string {
	return ""
}

func (e *ComposeExpander) StopAll() {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, stream := range e.streams {
		stream.stop()
	}
}

// reconcileStreams starts streams for new running containers and stops streams
// for containers that disappeared
func (e *ComposeExpander) reconcileStreams(send func(tea.Msg)) {
	if send == nil {
		return
	}

	e.mu.Lock()
	defer e.mu.Unlock()

	current := make(map[string]bool, len(e.containers))
	for _, c := range e.containers {
		if c.State == "running" {
			current[c.Service] = true
		}
	}

	// Stop streams for removed/stopped containers
	for service, stream := range e.streams {
		if !current[service] {
			stream.stop()
			delete(e.streams, service)
		}
	}

	// Start streams for new running containers
	for service := range current {
		if _, exists := e.streams[service]; !exists {
			stream := newLogStream(service, e.maxLines)
			stream.start(e.flags, send)
			e.streams[service] = stream
		}
	}
}

func (e *ComposeExpander) fetchCmd() tea.Cmd {
	flags := e.flags
	return func() tea.Msg {
		return fetchContainers(flags)
	}
}

func (e *ComposeExpander) pollCmd() tea.Cmd {
	flags := e.flags
	return tea.Every(pollInterval, func(t time.Time) tea.Msg {
		return fetchContainers(flags)
	})
}

func fetchContainers(flags ComposeFlags) containersMsg {
	args := flags.PsArgs()
	cmd := exec.Command("docker", args...)
	var stderr strings.Builder
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return containersMsg{err: err, stderr: stderr.String()}
	}

	containers := parseContainers(out)
	sort.Slice(containers, func(i, j int) bool {
		return containers[i].Service < containers[j].Service
	})
	return containersMsg{Containers: containers}
}

func parseContainers(data []byte) []Container {
	trimmed := strings.TrimSpace(string(data))
	if trimmed == "" {
		return nil
	}

	// Docker Compose v2.21+ outputs a JSON array
	if trimmed[0] == '[' {
		var containers []Container
		if err := json.Unmarshal([]byte(trimmed), &containers); err == nil {
			return containers
		}
	}

	// Older versions output one JSON object per line (NDJSON)
	var containers []Container
	for _, line := range strings.Split(trimmed, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var c Container
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			continue
		}
		containers = append(containers, c)
	}
	return containers
}

// IsComposeCommand checks if a shell command invokes docker compose
func IsComposeCommand(shell string) bool {
	return strings.Contains(shell, "docker compose")
}

// ParseComposeFlags extracts -f and --profile flags from a shell command
func ParseComposeFlags(shell string) ComposeFlags {
	var flags ComposeFlags
	words := strings.Fields(shell)
	for i := 0; i < len(words); i++ {
		switch words[i] {
		case "-f":
			if i+1 < len(words) {
				flags.Files = append(flags.Files, words[i+1])
				i++
			}
		case "--profile":
			if i+1 < len(words) {
				flags.Profiles = append(flags.Profiles, words[i+1])
				i++
			}
		}
	}
	return flags
}

var logsRe = regexp.MustCompile(`\blogs\b`)

// StripComposeLogs removes the `docker compose ... logs` portion from a compose
// shell command and replaces it with `tail -f /dev/null` to keep the process alive.
// Returns the original shell unchanged if no logs command is found.
func StripComposeLogs(shell string) string {
	parts := strings.Split(shell, "&&")
	var kept []string
	stripped := false
	for _, part := range parts {
		trimmed := strings.TrimSpace(part)
		if IsComposeCommand(trimmed) && logsRe.MatchString(trimmed) {
			stripped = true
			continue
		}
		kept = append(kept, trimmed)
	}
	if !stripped {
		return shell
	}
	kept = append(kept, "tail -f /dev/null")
	return strings.Join(kept, " && ")
}

// ContainerIconChar returns the status icon character for a container.
func ContainerIconChar(c Container) string {
	switch c.State {
	case "running":
		switch c.Health {
		case "unhealthy":
			return "✗" // crashed / problem
		case "starting":
			return "◌" // pending = warming up
		default:
			return "●" // running / healthy / no healthcheck
		}
	case "restarting":
		return "◌" // pending
	case "exited", "dead":
		return "✗" // crashed / error exit
	case "removing", "created", "paused":
		return "○" // stopped
	default:
		return "○"
	}
}

var (
	colorYellow = lipgloss.Color("#F7A501")
	colorGrey   = lipgloss.Color("#9BA1B2")
	colorGreen  = lipgloss.Color("#2DCC5D")
	colorRed    = lipgloss.Color("#F04438")
)

// ContainerIconColor returns the icon colour for a container
func ContainerIconColor(c Container) color.Color {
	switch c.State {
	case "running":
		switch c.Health {
		case "unhealthy":
			return colorRed
		case "starting":
			return colorYellow
		default:
			return colorGreen
		}
	case "restarting":
		return colorYellow
	case "exited", "dead":
		return colorRed
	default:
		return colorGrey
	}
}
