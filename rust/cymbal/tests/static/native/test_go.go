// Minimal Go test binary for ELF/DWARF symbolication testing, exercising Go
// function naming and mid-stack inlining. See build.sh.
package main

import "os"

//go:noinline
func process(value int) int {
	// Line 10 - this should be symbolicated
	return transform(value) + 1
}

// transform is small enough for the compiler to inline into process.
func transform(value int) int {
	doubled := value * 2
	doubled += value / 3
	// Line 16 - this should appear as an inlined frame
	return doubled + 5
}

func main() {
	// Line 22
	os.Exit(process(len(os.Args)) & 1)
}
