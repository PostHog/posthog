# Vendored from drain3 0.9.11 — https://github.com/IBM/Drain3
# Local changes: ruff-formatted/fixed.
#
# MIT License
#
# Copyright (c) 2020-2022 International Business Machines
# and the Drain3 project contributors.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ruff: noqa
# mypy: ignore-errors
# SPDX-License-Identifier: MIT

import re
import abc
from collections.abc import Collection
from typing import Optional


class AbstractMaskingInstruction(abc.ABC):
    def __init__(self, mask_with: str):
        self.mask_with = mask_with

    @abc.abstractmethod
    def mask(self, content: str, mask_prefix: str, mask_suffix: str) -> str:
        """
        Mask content according to this instruction and return the result.

        :param content: text to apply masking to
        :param mask_prefix: the prefix of any masks inserted
        :param mask_suffix: the suffix of any masks inserted
        """
        pass


class MaskingInstruction(AbstractMaskingInstruction):
    def __init__(self, pattern: str, mask_with: str):
        super().__init__(mask_with)
        self.regex = re.compile(pattern)

    @property
    def pattern(self):
        return self.regex.pattern

    def mask(self, content: str, mask_prefix: str, mask_suffix: str) -> str:
        mask = mask_prefix + self.mask_with + mask_suffix
        return self.regex.sub(mask, content)


# Alias for `MaskingInstruction`.
RegexMaskingInstruction = MaskingInstruction


class LogMasker:
    def __init__(
        self, masking_instructions: Collection[AbstractMaskingInstruction], mask_prefix: str, mask_suffix: str
    ):
        self.mask_prefix = mask_prefix
        self.mask_suffix = mask_suffix
        self.masking_instructions = masking_instructions
        self.mask_name_to_instructions = {}
        for mi in self.masking_instructions:
            self.mask_name_to_instructions.setdefault(mi.mask_with, [])
            self.mask_name_to_instructions[mi.mask_with].append(mi)

    def mask(self, content: str) -> str:
        for mi in self.masking_instructions:
            content = mi.mask(content, self.mask_prefix, self.mask_suffix)
        return content

    @property
    def mask_names(self) -> Collection[str]:
        return self.mask_name_to_instructions.keys()

    def instructions_by_mask_name(self, mask_name: str) -> Optional[Collection[AbstractMaskingInstruction]]:
        return self.mask_name_to_instructions.get(mask_name, [])


# Some masking examples
# ---------------------
#
# masking_instances = [
#    MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)(([0-9a-f]{2,}:){3,}([0-9a-f]{2,}))((?=[^A-Za-z0-9])|$)', "ID"),
#    MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})((?=[^A-Za-z0-9])|$)', "IP"),
#    MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)([0-9a-f]{6,} ?){3,}((?=[^A-Za-z0-9])|$)', "SEQ"),
#    MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)([0-9A-F]{4} ?){4,}((?=[^A-Za-z0-9])|$)', "SEQ"),
#
#    MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)(0x[a-f0-9A-F]+)((?=[^A-Za-z0-9])|$)', "HEX"),
#    MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)([\-\+]?\d+)((?=[^A-Za-z0-9])|$)', "NUM"),
#    MaskingInstruction(r'(?<=executed cmd )(".+?")', "CMD"),
# ]
