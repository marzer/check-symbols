#!/usr/bin/env python3
# This file is a part of marzer/check-symbols and is subject to the terms of the MIT license.
# Copyright (c) Mark Gillard <mark.gillard@outlook.com.au>
# See https://github.com/marzer/check-symbols/blob/main/LICENSE.txt for the full license text.
# SPDX-License-Identifier: MIT

import subprocess
from pathlib import Path

import pytest

SOURCES = Path(__file__).resolve().parent / 'sources'


def compile_cpp(*args):
    subprocess.run(['c++', '-std=c++17', *[str(arg) for arg in args]], check=True)


@pytest.fixture(scope='session')
def library(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp('library') / 'libfixture.so'
    compile_cpp(
        '-fPIC', '-shared', rf'-Wl,--version-script={SOURCES / "fixture.map"}', '-o', path, SOURCES / 'fixture.cpp'
    )
    return path


@pytest.fixture(scope='session')
def consumer(library, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp('consumer') / 'consumer'
    compile_cpp('-o', path, SOURCES / 'consumer.cpp', library)
    return path
