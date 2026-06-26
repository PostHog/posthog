# Vendored via drain3 0.9.11 — originally SimpleProfiler by David Ohana.
# Local changes: ruff-formatted/fixed; ty annotation fixes. Apache-2.0; full license text at
# https://www.apache.org/licenses/LICENSE-2.0 (SPDX identifier + upstream source retained below).
# ruff: noqa
# mypy: ignore-errors
# SPDX-License-Identifier: Apache-2.0
# Based on https://github.com/davidohana/SimpleProfiler/blob/main/python/simple_profiler.py

import os
import time
from abc import ABC, abstractmethod


class Profiler(ABC):
    @abstractmethod
    def start_section(self, section_name: str):
        pass

    @abstractmethod
    def end_section(self, section_name=""):
        pass

    @abstractmethod
    def report(self, period_sec=30):
        pass


class NullProfiler(Profiler):
    """A no-op profiler. Use it instead of SimpleProfiler in case you want to disable profiling."""

    def start_section(self, section_name: str):
        pass

    def end_section(self, section_name=""):
        pass

    def report(self, period_sec=30):
        pass


class SimpleProfiler(Profiler):
    def __init__(self, reset_after_sample_count=0, enclosing_section_name="total", printer=print, report_sec=30):
        self.printer = printer
        self.enclosing_section_name = enclosing_section_name
        self.reset_after_sample_count = reset_after_sample_count
        self.report_sec = report_sec

        self.section_to_stats = {}
        self.last_report_timestamp_sec = time.time()
        self.last_started_section_name = ""

    def start_section(self, section_name: str):
        """Start measuring a section"""

        if not section_name:
            raise ValueError("Section name is empty")
        self.last_started_section_name = section_name

        section = self.section_to_stats.get(section_name, None)
        if section is None:
            section = ProfiledSectionStats(section_name)
            self.section_to_stats[section_name] = section

        if section.start_time_sec != 0:
            raise ValueError(f"Section {section_name} is already started")

        section.start_time_sec = time.time()

    def end_section(self, name=""):
        """End measuring a section. Leave section name empty to end the last started section."""

        now = time.time()

        section_name = name
        if not name:
            section_name = self.last_started_section_name

        if not section_name:
            raise ValueError("Neither section name is specified nor a section is started")

        section: ProfiledSectionStats | None = self.section_to_stats.get(section_name, None)
        if section is None:
            raise ValueError(f"Section {section_name} does not exist")

        if section.start_time_sec == 0:
            raise ValueError(f"Section {section_name} was not started")

        took_sec = now - section.start_time_sec
        if 0 < self.reset_after_sample_count == section.sample_count:
            section.sample_count_batch = 0
            section.total_time_sec_batch = 0

        section.sample_count += 1
        section.total_time_sec += took_sec
        section.sample_count_batch += 1
        section.total_time_sec_batch += took_sec
        section.start_time_sec = 0

    def report(self, period_sec=30):
        """Print results using [printer] function. By default prints to stdout."""
        if time.time() - self.last_report_timestamp_sec < period_sec:
            return False

        enclosing_time_sec = 0
        if self.enclosing_section_name:
            enclosing_section: ProfiledSectionStats | None = self.section_to_stats.get(
                self.enclosing_section_name, None
            )
            if enclosing_section:
                enclosing_time_sec = enclosing_section.total_time_sec

        include_batch_rates = self.reset_after_sample_count > 0

        sections = self.section_to_stats.values()
        sorted_sections = sorted(sections, key=lambda it: it.total_time_sec, reverse=True)
        lines = map(lambda it: it.to_string(enclosing_time_sec, include_batch_rates), sorted_sections)
        text = os.linesep.join(lines)
        self.printer(text)

        self.last_report_timestamp_sec = time.time()
        return True


class ProfiledSectionStats:
    def __init__(
        self,
        section_name,
        start_time_sec=0,
        sample_count=0,
        total_time_sec=0,
        sample_count_batch=0,
        total_time_sec_batch=0,
    ):
        self.section_name = section_name
        self.start_time_sec = start_time_sec
        self.sample_count = sample_count
        self.total_time_sec = total_time_sec
        self.sample_count_batch = sample_count_batch
        self.total_time_sec_batch = total_time_sec_batch

    def to_string(self, enclosing_time_sec: int, include_batch_rates: bool):
        took_sec_text = f"{self.total_time_sec:>8.2f} s"
        if enclosing_time_sec > 0:
            took_sec_text += f" ({100 * self.total_time_sec / enclosing_time_sec:>6.2f}%)"

        ms_per_k_samples = f"{1000000 * self.total_time_sec / self.sample_count: 7.2f}"

        if self.total_time_sec > 0:
            samples_per_sec = f"{self.sample_count / self.total_time_sec: 15,.2f}"
        else:
            samples_per_sec = "N/A"

        if include_batch_rates:
            ms_per_k_samples += f" ({1000000 * self.total_time_sec_batch / self.sample_count_batch: 7.2f})"
            if self.total_time_sec_batch > 0:
                samples_per_sec += f" ({self.sample_count_batch / self.total_time_sec_batch: 15,.2f})"
            else:
                samples_per_sec += " (N/A)"

        return (
            f"{self.section_name: <15}: took {took_sec_text}, "
            f"{self.sample_count: >10,} samples, "
            f"{ms_per_k_samples} ms / 1000 samples, "
            f"{samples_per_sec} hz"
        )
