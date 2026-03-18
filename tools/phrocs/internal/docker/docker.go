package docker

import (
	"bufio"
	"encoding/json"
	"fmt"
	"image/color"
	"os"
	"os/exec"
	"sort"
	"strings"
	"sync"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	sharedpalette "github.com/posthog/posthog/phrocs/internal/palette"
)

// DockerContainer represents a container from docker compose ps
type DockerContainer struct {
	Service string
	Status  string
	State   string
}

type ContainerListMsg struct {
	Containers []DockerContainer
}

type ContainerPollTickMsg struct{}

type ContainerLogLineMsg struct {
	Service string
	Line    string
}

// containerLogStream manages a log-following subprocess for a single container.
// Pointer-based so it survives Bubble Tea's value-copy Model updates.
type ContainerLogStream struct {
	mu      sync.Mutex
	cmd     *exec.Cmd
	stopped bool
}

func (s *ContainerLogStream) Stop() {
	if s == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stopped = true
	if s.cmd != nil && s.cmd.Process != nil {
		_ = s.cmd.Process.Kill()
	}
}

func IsDockerComposeShell(shell string) bool {
	return strings.Contains(shell, "docker compose") || strings.Contains(shell, "docker-compose")
}

// ComposeArgs holds the flags needed to address the right compose project
type ComposeArgs struct {
	Files    []string // -f / --file values
	Profiles []string // --profile values
}

// ParseComposeArgs extracts all -f/--file and --profile flags from a shell
// command string so they can be forwarded to docker compose subcommands.
func ParseComposeArgs(shell string) ComposeArgs {
	parts := strings.Fields(shell)
	var args ComposeArgs
	for i := 0; i < len(parts); i++ {
		switch {
		case (parts[i] == "-f" || parts[i] == "--file") && i+1 < len(parts):
			args.Files = append(args.Files, parts[i+1])
			i++
		case parts[i] == "--profile" && i+1 < len(parts):
			args.Profiles = append(args.Profiles, parts[i+1])
			i++
		case strings.HasPrefix(parts[i], "--file="):
			args.Files = append(args.Files, strings.TrimPrefix(parts[i], "--file="))
		case strings.HasPrefix(parts[i], "--profile="):
			args.Profiles = append(args.Profiles, strings.TrimPrefix(parts[i], "--profile="))
		}
	}
	return args
}

// StripComposeLogsTail removes a trailing "docker compose ... logs ..." segment
// from a &&-chained shell command. This prevents the parent process from
// tailing all container logs when phrocs streams them individually per container.
func StripComposeLogsTail(shell string) string {
	segments := strings.Split(shell, "&&")
	if len(segments) < 2 {
		return shell
	}
	last := strings.TrimSpace(segments[len(segments)-1])
	if IsDockerComposeShell(last) && strings.Contains(last, "logs") {
		return strings.TrimRight(strings.Join(segments[:len(segments)-1], "&&"), " ")
	}
	return shell
}

func composeBaseArgs(args ComposeArgs) []string {
	base := []string{"compose"}
	for _, f := range args.Files {
		base = append(base, "-f", f)
	}
	for _, p := range args.Profiles {
		base = append(base, "--profile", p)
	}
	return base
}

func FetchContainerList(args ComposeArgs) tea.Cmd {
	return func() tea.Msg {
		base := composeBaseArgs(args)
		args := append(base, "ps", "--format", "json")
		cmd := exec.Command("docker", args...)
		out, err := cmd.Output()
		if err != nil {
			return ContainerListMsg{}
		}
		var containers []DockerContainer
		for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if line == "" {
				continue
			}
			var raw struct {
				Service string `json:"Service"`
				Status  string `json:"Status"`
				State   string `json:"State"`
			}
			if json.Unmarshal([]byte(line), &raw) == nil {
				containers = append(containers, DockerContainer{
					Service: raw.Service,
					Status:  raw.Status,
					State:   raw.State,
				})
			}
		}
		sort.Slice(containers, func(i, j int) bool {
			return containers[i].Service < containers[j].Service
		})
		return ContainerListMsg{Containers: containers}
	}
}

func PollContainersTick() tea.Cmd {
	return tea.Tick(5*time.Second, func(time.Time) tea.Msg {
		return ContainerPollTickMsg{}
	})
}

const MaxContainerLogLines = 5000

func StartContainerLogStream(composeArgs ComposeArgs, service string, send func(tea.Msg)) *ContainerLogStream {
	stream := &ContainerLogStream{}
	base := composeBaseArgs(composeArgs)
	args := append(base, "logs", "-f", "--tail=200", "--no-log-prefix", service)
	cmd := exec.Command("docker", args...)

	pr, pw, err := os.Pipe()
	if err != nil {
		return stream
	}
	cmd.Stdout = pw
	cmd.Stderr = pw

	if err := cmd.Start(); err != nil {
		_ = pr.Close()
		_ = pw.Close()
		return stream
	}

	stream.mu.Lock()
	stream.cmd = cmd
	stream.mu.Unlock()

	_ = pw.Close()

	go func() {
		scanner := bufio.NewScanner(pr)
		scanner.Buffer(make([]byte, 64*1024), 1024*1024)
		for scanner.Scan() {
			stream.mu.Lock()
			stopped := stream.stopped
			stream.mu.Unlock()
			if stopped {
				break
			}
			send(ContainerLogLineMsg{
				Service: service,
				Line:    scanner.Text(),
			})
		}
		if err := scanner.Err(); err != nil {
			send(ContainerLogLineMsg{
				Service: service,
				Line:    fmt.Sprintf("[log stream error: %v]", err),
			})
		}
		_ = pr.Close()
		_ = cmd.Wait()
	}()

	return stream
}

func RenderContainerStatusTable(containers []DockerContainer, width int) string {
	if len(containers) == 0 {
		return "  Waiting for containers..."
	}

	svcW := 7
	stateW := 5
	statusW := 6

	for _, c := range containers {
		if len(c.Service) > svcW {
			svcW = len(c.Service)
		}
		if len(c.State) > stateW {
			stateW = len(c.State)
		}
		if len(c.Status) > statusW {
			statusW = len(c.Status)
		}
	}

	maxSvcW := width / 3
	if maxSvcW > 0 && svcW > maxSvcW {
		svcW = maxSvcW
	}

	var sb strings.Builder
	sb.WriteByte('\n')
	header := fmt.Sprintf("  %-*s  %-*s  %s", svcW, "SERVICE", stateW, "STATE", "STATUS")
	sb.WriteString(lipgloss.NewStyle().Bold(true).Foreground(sharedpalette.ColorWhite).Render(header))
	sb.WriteByte('\n')
	sb.WriteString(lipgloss.NewStyle().Foreground(sharedpalette.ColorDarkGrey).Render("  " + strings.Repeat("─", max(width-4, 0))))
	sb.WriteByte('\n')

	for _, c := range containers {
		var stateColor color.Color
		switch c.State {
		case "running":
			stateColor = sharedpalette.ColorGreen
		case "exited":
			stateColor = sharedpalette.ColorRed
		default:
			stateColor = sharedpalette.ColorYellow
		}

		svc := c.Service
		if len(svc) > svcW {
			svc = svc[:svcW]
		}
		sb.WriteString("  ")
		sb.WriteString(lipgloss.NewStyle().Foreground(sharedpalette.ColorWhite).Render(fmt.Sprintf("%-*s", svcW, svc)))
		sb.WriteString("  ")
		sb.WriteString(lipgloss.NewStyle().Foreground(stateColor).Render(fmt.Sprintf("%-*s", stateW, c.State)))
		sb.WriteString(lipgloss.NewStyle().Foreground(sharedpalette.ColorGrey).Render(fmt.Sprintf("  %s", c.Status)))
		sb.WriteByte('\n')
	}

	return sb.String()
}

func ContainerStateIcon(state string) string {
	switch state {
	case "running":
		return sharedpalette.IconRunning
	case "exited":
		return sharedpalette.IconCrashed
	case "paused":
		return sharedpalette.IconPending
	default:
		return sharedpalette.IconStopped
	}
}

func ContainerStateColor(state string) color.Color {
	switch state {
	case "running":
		return sharedpalette.ColorGreen
	case "exited":
		return sharedpalette.ColorRed
	case "paused":
		return sharedpalette.ColorYellow
	default:
		return sharedpalette.ColorGrey
	}
}
