from products.review_hog.backend.reviewer.tools.github_meta import PRFile


def prepare_code_context(chunk_filenames: list[str], pr_files: list[PRFile]) -> str:
    """Prepare context with specific line ranges for changed code."""
    claude_code_context_lines = []
    for filename in chunk_filenames:
        # Find the corresponding PRFile to get changes
        pr_file = next((f for f in pr_files if f.filename == filename), None)
        if pr_file and pr_file.changes:
            # Collect line ranges for additions and deletions only
            line_ranges = []
            for change in pr_file.changes:
                if change.type not in ["addition", "deletion"]:
                    continue
                # Use new line numbers for additions, old for deletions
                if change.type == "addition" and change.new_start_line and change.new_end_line:
                    line_ranges.append((change.new_start_line, change.new_end_line))
                elif change.type == "deletion" and change.old_start_line and change.old_end_line:
                    line_ranges.append((change.old_start_line, change.old_end_line))

            # Merge overlapping or adjacent ranges
            if line_ranges:
                line_ranges.sort()
                merged_ranges: list[tuple[int, int]] = []
                for start, end in line_ranges:
                    if merged_ranges and start <= merged_ranges[-1][1] + 1:
                        # Merge with previous range
                        merged_ranges[-1] = (
                            merged_ranges[-1][0],
                            max(merged_ranges[-1][1], end),
                        )
                    else:
                        merged_ranges.append((start, end))
                # Generate context lines with specific ranges
                for start, end in merged_ranges:
                    if start == end:
                        claude_code_context_lines.append(f"@{filename}#L{start}")
                    else:
                        claude_code_context_lines.append(f"@{filename}#L{start}-{end}")
            else:
                # No changes, include whole file
                claude_code_context_lines.append(f"@{filename}")
        else:
            # No PRFile found or no changes, include whole file
            claude_code_context_lines.append(f"@{filename}")
    return "\n".join(claude_code_context_lines)
