#!/usr/bin/env python3
# This file is a part of marzer/check-symbols and is subject to the terms of the MIT license.
# Copyright (c) Mark Gillard <mark.gillard@outlook.com.au>
# See https://github.com/marzer/check-symbols/blob/main/LICENSE.txt for the full license text.
# SPDX-License-Identifier: MIT

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which('c++') is None or shutil.which('nm') is None, reason='needs a C++ compiler and nm'
)

EXPORTED = [
    'fixture::add',
    'fixture::counter',
    'fixture::dispatched',
    'fixture::doubler::operator()',
    'fixture::not_imported',
    'fixture::operator*',
    'fixture::seed',
    'fixture::shape::~shape',
    'fixture::square::area',
    'fixture::square::operator bool',
    'fixture::square::operator delete',
    'fixture::square::operator new',
    'fixture::square::square',
    'fixture::table',
    'fixture::twice<int>',
    'versioned_answer',
]

ABI_SYMBOLS = [
    'fixture::shape::$typeinfo',
    'fixture::shape::$typeinfo_name',
    'fixture::shape::$vtable',
    'fixture::square::$typeinfo',
    'fixture::square::$typeinfo_name',
    'fixture::square::$vtable',
]

FIXTURE_ONLY = r'^(fixture::|versioned_answer$)'
WEAK = r'thrice'


def run(*args, stdin=None, cwd=None, env=None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in (os.environ if env is None else env).items() if k != 'PYCHARM_HOSTED'}
    return subprocess.run(
        [sys.executable, str(REPO / 'src' / '__main__.py'), *[str(arg) for arg in args]],
        input=stdin,
        capture_output=True,
        encoding='utf-8',
        cwd=cwd,
        env=env,
        timeout=60,
    )


def assert_friendly_error(result: subprocess.CompletedProcess, message: str):
    assert result.returncode == 255
    assert message in result.stderr
    assert 'internal bug' not in result.stderr


@pytest.fixture(scope='session')
def symbol_list(library) -> list[str]:
    result = run(library)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def write_list(path: Path, symbols) -> Path:
    path.write_text(''.join(f'{s}\n' for s in symbols), encoding='utf-8')
    return path


def test_version_matches_version_file():
    result = run('--version')
    assert result.returncode == 0
    assert result.stdout.strip() == (REPO / 'VERSION').read_text(encoding='utf-8').strip()


def test_list_mode_prints_sorted_normalised_symbols(symbol_list):
    assert symbol_list == sorted(set(symbol_list))
    assert symbol_list == EXPORTED


def test_list_mode_adds_vtables_and_typeinfo_with_abi_symbols(library):
    result = run(library, '--abi-symbols')
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == sorted(EXPORTED + ABI_SYMBOLS)


def test_list_mode_output_round_trips_through_check(library, symbol_list, tmp_path):
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', symbol_list))
    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == f'found {len(symbol_list)} / {len(symbol_list)} expected symbols.'


def test_list_mode_output_round_trips_through_check_with_abi_symbols(library, tmp_path):
    symbols = run(library, '--abi-symbols').stdout.splitlines()
    result = run(library, '--abi-symbols', '--check', write_list(tmp_path / 'symbols.txt', symbols))
    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == f'found {len(symbols)} / {len(symbols)} expected symbols.'


def test_check_ignores_abi_symbols_in_an_old_check_file(library, symbol_list, tmp_path):
    lines = [*symbol_list, *ABI_SYMBOLS, 'name for fixture::shape::$typeinfo']
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', lines))
    assert result.returncode == 0, result.stdout
    assert '::$' not in result.stdout
    assert result.stdout.splitlines()[-1] == f'found {len(symbol_list)} / {len(symbol_list)} expected symbols.'


def test_check_with_abi_symbols_reports_vtables_missing_from_the_list(library, symbol_list, tmp_path):
    result = run(library, '--abi-symbols', '--check', write_list(tmp_path / 'symbols.txt', symbol_list))
    assert result.returncode == 2
    assert '[XX] fixture::square::$vtable' in result.stdout.splitlines()


def test_check_reads_the_list_from_stdin(library, symbol_list):
    result = run(library, '--check', '-', stdin='\n'.join(symbol_list))
    assert result.returncode == 0, result.stdout
    assert 'with those listed in -:' in result.stdout


def test_check_sets_bit_1_for_missing_symbols(library, symbol_list, tmp_path):
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', [*symbol_list, 'fixture::removed']))
    assert result.returncode == 1
    assert '[??] fixture::removed - not found' in result.stdout


def test_check_sets_bit_2_for_unexpected_symbols(library, symbol_list, tmp_path):
    symbols = [s for s in symbol_list if s != 'fixture::not_imported']
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', symbols))
    assert result.returncode == 2
    assert '[XX] fixture::not_imported' in result.stdout


def test_check_sets_both_bits_for_missing_and_unexpected_symbols(library, symbol_list, tmp_path):
    symbols = [*[s for s in symbol_list if s != 'fixture::not_imported'], 'fixture::removed']
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', symbols))
    assert result.returncode == 3


def test_check_file_comments_and_blank_lines_are_ignored(library, symbol_list, tmp_path):
    lines = ['# expected exports', '', '; for libfixture.so', '// one per line', '']
    lines += [f'{s}  # exported' for s in symbol_list]
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', lines))
    assert result.returncode == 0, result.stdout


def test_check_file_stray_parenthesis_is_reported_missing_without_crashing(library, symbol_list, tmp_path):
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', [')', ') const', *symbol_list]))
    assert result.returncode == 1
    assert '[??] ) - not found' in result.stdout
    assert '[??] ) const - not found' in result.stdout
    assert 'internal bug' not in result.stderr


def test_include_patterns_must_all_match(library):
    result = run(library, '--include', r'^fixture::', r'operator')
    assert result.returncode == 0
    assert result.stdout.splitlines() == [s for s in EXPORTED if s.startswith('fixture::') and 'operator' in s]


def test_exclude_patterns_drop_any_match(library):
    result = run(library, '--exclude', r'operator', r'^fixture::s')
    assert result.returncode == 0
    assert result.stdout.splitlines() == [s for s in EXPORTED if 'operator' not in s and not s.startswith('fixture::s')]


def test_include_filters_the_check_list_too(library, symbol_list, tmp_path):
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', symbol_list), '--include', r'^fixture::sq')
    assert result.returncode == 0, result.stdout
    assert 'fixture::add' not in result.stdout
    assert '[OK] fixture::square::operator bool' in result.stdout


def test_diff_reports_imported_unused_and_missing_symbols(library, consumer):
    result = run(library, '--diff', consumer)
    assert result.returncode == 1
    stdout = result.stdout.splitlines()
    assert '[OK] versioned_answer' in stdout
    assert '[OK] fixture::square::operator bool' in stdout
    assert '[OK] fixture::square::operator new' in stdout
    assert '[OK] fixture::square::operator delete' in stdout
    assert '[OK] fixture::doubler::operator()' in stdout
    assert '[OK] fixture::dispatched' in stdout
    assert '[--] fixture::not_imported' in stdout
    assert '[--] fixture::table' in stdout
    assert '[??] fixture::thrice<int>' in stdout
    assert '[??] __libc_start_main' in stdout


def test_diff_exits_zero_when_every_filtered_import_is_exported(library, consumer):
    result = run(library, '--diff', consumer, '--include', FIXTURE_ONLY, '--exclude', WEAK)
    assert result.returncode == 0, result.stdout
    assert '[??]' not in result.stdout
    assert '[OK] fixture::twice<int>' in result.stdout


def test_diff_does_not_count_unique_globals_defined_by_the_consumer_as_imports(library, consumer):
    assert 'fixture::shared' not in run(library, '--diff', consumer).stdout


def test_diff_lists_abi_symbols_only_with_abi_symbols(library, consumer):
    assert '::$' not in run(library, '--diff', consumer).stdout
    result = run(library, '--diff', consumer, '--abi-symbols', '--include', FIXTURE_ONLY, '--exclude', WEAK)
    assert result.returncode == 0, result.stdout
    stdout = result.stdout.splitlines()
    assert '[OK] fixture::shape::$typeinfo' in stdout
    assert '[--] fixture::square::$vtable' in stdout


def test_diff_and_check_exit_bits_combine(library, consumer, symbol_list, tmp_path):
    symbols = [s for s in symbol_list if s != 'fixture::not_imported']
    result = run(library, '--diff', consumer, '--check', write_list(tmp_path / 'symbols.txt', symbols))
    assert result.returncode == 3


def test_directory_discovery_picks_the_first_library_in_sorted_order(library, symbol_list, tmp_path):
    (tmp_path / 'aaa.so').mkdir()
    for n in range(10):
        shutil.copyfile(library, tmp_path / f'lib{n}.so')
    result = run('--check', '-', stdin='\n'.join(symbol_list), cwd=tmp_path)
    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[0].endswith(f'{os.sep}lib0.so with those listed in -:')


def test_missing_library_is_a_friendly_error(tmp_path):
    assert_friendly_error(run(tmp_path / 'libmissing.so'), 'did not exist or was not a file')


def test_directory_without_a_library_is_a_friendly_error(tmp_path):
    assert_friendly_error(run(tmp_path), 'could not find a shared library in')


def test_missing_consumer_is_a_friendly_error(library, tmp_path):
    assert_friendly_error(run(library, '--diff', tmp_path / 'missing'), 'did not exist or was not a file')


def test_missing_check_file_is_a_friendly_error(library, tmp_path):
    assert_friendly_error(run(library, '--check', tmp_path / 'missing.txt'), 'did not exist or was not a file')


def test_check_file_without_symbols_is_a_friendly_error(library, tmp_path):
    result = run(library, '--check', write_list(tmp_path / 'symbols.txt', ['# nothing here']))
    assert_friendly_error(result, 'was empty')


def test_nm_failure_is_a_friendly_error(tmp_path):
    (tmp_path / 'libjunk.so').write_text('not an elf file\n', encoding='utf-8')
    assert_friendly_error(run(tmp_path / 'libjunk.so'), 'nm exited with code')


def test_missing_nm_is_reported_as_not_found(library, tmp_path):
    result = run(library, env={**os.environ, 'PATH': str(tmp_path)})
    assert_friendly_error(result, 'nm was not found on the PATH')


def test_invalid_regex_is_a_friendly_error(library):
    assert_friendly_error(run(library, '--include', '('), 'invalid regular expression')
