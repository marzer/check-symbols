#!/usr/bin/env python3
# This file is a part of marzer/check-symbols and is subject to the terms of the MIT license.
# Copyright (c) Mark Gillard <mark.gillard@outlook.com.au>
# See https://github.com/marzer/check-symbols/blob/main/LICENSE.txt for the full license text.
# SPDX-License-Identifier: MIT

import argparse
import re
import subprocess
import sys
import typing
from io import StringIO
from pathlib import Path

import colorama
import misk

from . import paths
from .colour import *
from .version import *


class Error(Exception):
    pass


def error(text):
    print(rf"{bright(rf'error:', 'red')} {text}", file=sys.stderr)


def re_sub_all(pattern, repl, string, count=0, flags=0) -> str:
    pre = string
    string = re.sub(pattern, repl, string, count=count, flags=flags)
    while pre != string:
        pre = string
        string = re.sub(pattern, repl, string, count=count, flags=flags)
    return string


STD_DEMANGLED = []
for prefix, type in (('', 'char'), ('w', 'wchar_t'), ('u8', 'char8_t'), ('u16', 'char16_t'), ('u32', 'char32_t')):
    STD_DEMANGLED.append(
        (re.compile(rf'<\s*{type}\s*,\s*std::char_traits<{type}>\s*,\s*std::allocator<{type}>\s*>'), rf'<{type}>')
    )
    STD_DEMANGLED.append((re.compile(rf'<\s*{type}\s*,\s*std::char_traits<{type}>\s*>'), rf'<{type}>'))
    STD_DEMANGLED.append(
        (re.compile(rf'std::basic_(i|o)?string(stream|buf)?<\s*{type}\s*>'), rf'std::{prefix}\1string\2')
    )
for prefix, type in (('', 'char'), ('w', 'wchar_t')):
    STD_DEMANGLED.append(
        (re.compile(rf'std::basic_((?:if|of|f)?stream|(?:file|stream)buf|ios)<\s*{type}\s*>'), rf'std::{prefix}\1')
    )

OPERATOR = re.compile(r'\boperator\b')
NESTED = r'(?:[^()]|\([^()]*\))*'
POINTER_DECLARATOR = re.compile(rf'\((?:{NESTED}::)?[*&]{NESTED}\)$')

EXPORTED_CATEGORIES = (r'B', r'D', r'R', r'T', r'i')
WEAK_CATEGORIES = (r'V', r'W', r'u')
ABI_SYMBOL = re.compile(
    r'(?:(?:vtable|VTT|construction vtable|typeinfo|typeinfo name|typeinfo fn|guard variable|TLS init function'
    r'|TLS wrapper function|transaction clone|reference temporary #\d+|template parameter object) for'
    r'|(?:virtual|non-virtual|covariant return) thunk to|initializer for module)[ (]|_ZGR'
)
NORMALISED_ABI_SYMBOL = re.compile(
    r'.+::\$(?:vtable|VTT|typeinfo|typeinfo_name)|reference temporary'
    r'|(?:(?:return )?thunk to|(?:variable|clone|init function|wrapper function|parameter object) for)[ (].+'
)


def remove_comment(line: str) -> str:
    depth = 0
    for pos, c in enumerate(line):
        if c in '{[(':
            depth += 1
        elif c in '}])':
            depth = max(depth - 1, 0)
        elif depth == 0 and (c in '#;' or line.startswith('//', pos)):
            return line[:pos]
    return line


def strip_return_type(name: str) -> str:
    depth = 0
    for pos, c in enumerate(name):
        if c in '([{<':
            depth += 1
        elif c in ')]}>':
            depth -= 1
        elif depth != 0:
            continue
        elif c in ' \t':
            name = name[pos:].strip()
            return re_sub_all(r'^\s*(?:const|volatile|const\s+volatile|volatile\s+const)\s*&\s+(.+?)\s*$', r'\1', name)
        elif OPERATOR.match(name, pos):
            return name
    return name


def strip_signature(name: str) -> str:
    # find parameter list
    # (regex alone is not enough here - a parens-balancing reverse parse is required)
    m = re.search(r'\)(?:\s*(?:const|volatile|noexcept|&&?))*$', name)
    if not m:
        return name
    depth = 0
    for pos in range(m.start(), -1, -1):
        if name[pos] == ')':
            depth += 1
        elif name[pos] == '(':
            depth -= 1
            if depth != 0:
                continue
            head = name[:pos].rstrip()
            if re.search(r'\boperator$', head):
                return strip_return_type(name[: m.start() + 1])
            if OPERATOR.search(head) and POINTER_DECLARATOR.search(head):
                return name
            return strip_return_type(head)
    return name


def make_symbol_list(s, undefined_only=False, comments=False, abi_symbols=False) -> list[str]:
    # remove c++11 abi tags
    s = str(s).replace('[abi:cxx11]', '').replace('std::__cxx11::', 'std::').strip()
    # demangle std templated symbol names with their aliases
    for expr, sub in STD_DEMANGLED:
        s = expr.sub(sub, s)
    # normalize whitespace
    s = re_sub_all(r'[ \t][ \t]+', ' ', s)
    # split and trim per-line
    s = [i.strip() for i in re.split(r'[\r\n]', s)]
    # remove comments
    if comments:
        s = [remove_comment(i) for i in s]
    # remove any categorized symbols we don't want (https://linux.die.net/man/1/nm)
    allowed_categories = (r'U',) if undefined_only else EXPORTED_CATEGORIES
    # weak and unique definitions are mostly template instantiations and inline functions and vary with the
    # toolchain; the only ones worth listing are the vtables and typeinfo behind --abi-symbols
    weak_abi_symbols = abi_symbols and not undefined_only
    s2 = []
    for i in s:
        m = re.match(r'^(?:[0-9a-fA-F]{6,32}\s+)?([a-zA-Z?])\s+(.+?)$', i)
        if m:
            category, i = m[1], m[2].strip()
            if category not in allowed_categories and not (
                weak_abi_symbols and category in WEAK_CATEGORIES and ABI_SYMBOL.match(i)
            ):
                continue
        if not abi_symbols and ABI_SYMBOL.match(i):
            continue
        s2.append(i)
    s = s2
    # normalize spacing and weird oddities
    s = [re_sub_all(r'^(.+?)@@?\s*[a-zA-Z][a-zA-Z0-9._+~-]*\s*$', r'\1', i) for i in s]  # @IMPORT tags
    s = [re_sub_all(r'>\s+>', '>>', i) for i in s]
    s = [re_sub_all(r',\s\s+([a-zA-Z0-9_])', r', \1', i) for i in s]
    s = [re_sub_all(r'([a-zA-Z0-9_>])\s+\(', r'\1(', i) for i in s]
    # normalize vtable and type info representations
    s = [re.sub(r'^\s*(.+?)\s*::\s*\$\s*(vtable|typeinfo_name|typeinfo|VTT)\s*$', r'\1::$\2', i).strip() for i in s]
    s = [re.sub(r'^\s*\[\s*(vtable|typeinfo_name|typeinfo|VTT)\s*\]\s*(.+?)$', r'\2::$\1', i).strip() for i in s]
    if abi_symbols:
        s = [re.sub(r'^\s*typeinfo\s+name\s+(?:for\s+)?(.+?)$', r'\1::$typeinfo_name', i).strip() for i in s]
        s = [re.sub(r'^\s*(vtable|typeinfo|VTT)\s+(?:for\s+)?(.+?)$', r'\2::$\1', i).strip() for i in s]
    elif comments:
        s = [i for i in s if not NORMALISED_ABI_SYMBOL.fullmatch(i)]
    # special handling for functions
    s = [strip_signature(i) for i in s]
    # remove blank lines
    s = [i for i in [j.strip() for j in s] if i]
    # remove more implementation details
    s = [i for i in s if not re.fullmatch(r'(?:__bss_start|_edata|_end|_fini|_init)', i)]
    # de-duplicate and sort
    return sorted(set(s))


def matches_all(s: str, pattern) -> bool:
    if pattern:
        for p in pattern:
            if not p.search(s):
                return False
    return True


def matches_any(s: str, pattern) -> bool:
    if pattern:
        for p in pattern:
            if p.search(s):
                return True
    return False


def filter_symbols(symbols: list[str], include, exclude) -> list[str]:
    return [s for s in symbols if matches_all(s, include) and not matches_any(s, exclude)]


def diff_symbols(exported: list[str], imported: list[str]) -> tuple[list[str], list[str], list[str]]:
    exported_set = set(exported)
    imported_set = set(imported)
    used = [s for s in exported if s in imported_set]
    unused = [s for s in exported if s not in imported_set]
    missing = [s for s in imported if s not in exported_set]
    return used, unused, missing


def check_symbols(exported: list[str], expected: list[str]) -> tuple[list[str], list[str]]:
    exported_set = set(exported)
    expected_set = set(expected)
    missing = [s for s in expected if s not in exported_set]
    unexpected = [s for s in exported if s not in expected_set]
    return missing, unexpected


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=r"Command-line utility for checking ELF symbols.",
        epilog=rf'v{VERSION_STRING} - github.com/marzer/check-symbols',
    )
    parser.add_argument(r'--version', action=r'store_true', help=r"print the version and exit", dest=r'print_version')
    parser.add_argument(r'--where', action=r'store_true', help=argparse.SUPPRESS)
    parser.add_argument(
        r"lib",
        type=Path,
        nargs=r'?',
        default=None,
        metavar=r"<path>",
        help="path to the shared library, or a directory containing it (default: discover automatically)",
    )
    parser.add_argument(
        r"--check",
        type=Path,
        default=None,
        metavar=r"<path>",
        help='path to a text file containing a list of expected symbols (one per line). use a dash (\'-\') to read from stdin.',
    )
    parser.add_argument(
        r"--diff",
        type=Path,
        default=None,
        metavar=r"<path>",
        help=rf"compiled executable or shared library expected to consume the symbols",
    )
    parser.add_argument(
        r"--include",
        type=str,
        nargs='+',
        metavar=r"<regex>",
        help=rf"one or more regular expressions to select the listed/checked symbols.",
    )
    parser.add_argument(
        r"--exclude",
        type=str,
        nargs='+',
        metavar=r"<regex>",
        help=rf"one or more regular expressions to exclude from the listed/checked symbols.",
    )
    parser.add_argument(
        r"--abi-symbols",
        action=r'store_true',
        help=r"include compiler-generated ABI symbols such as vtables, typeinfo, thunks and guard variables",
    )
    return parser.parse_args(argv)


def find_library(path: typing.Optional[Path]) -> Path:
    if path is None:
        path = Path.cwd()
    if path.is_file():
        return path
    if not path.is_dir():
        raise Error(rf"shared library {bright(path)} did not exist or was not a file")
    for item in sorted(path.iterdir()):
        if item.name.endswith('.so') and item.is_file():
            return item
    raise Error(rf"could not find a shared library in {bright(path)}")


def compile_patterns(patterns: typing.Optional[list[str]]) -> list[re.Pattern]:
    try:
        return [re.compile(p) for p in patterns or []]
    except re.error as err:
        raise Error(rf"invalid regular expression {bright(err.pattern)}: {err}") from None


def run_nm(path: Path, undefined_only=False, abi_symbols=False) -> list[str]:
    try:
        result = subprocess.run([r'nm', r'-PBDCg', str(path)], capture_output=True, encoding='utf-8')
    except FileNotFoundError:
        raise Error(rf"{bright('nm')} was not found on the PATH") from None
    if result.returncode == 0:
        return make_symbol_list(result.stdout, undefined_only=undefined_only, abi_symbols=abi_symbols)
    outputs = ''
    for name, text in (('stdout', result.stdout), ('stderr', result.stderr)):
        if text:
            outputs += f'\n  {bright(name)}:\n'
            outputs += "\n".join([rf'    {i.strip()}' for i in text.split('\n') if i.strip()])
    raise Error(rf"{bright('nm')} exited with code {bright(result.returncode)}{outputs}")


def read_check_file(path: Path) -> str:
    if path == Path('-'):
        return sys.stdin.read()
    if not path.is_file():
        raise Error(rf"expected symbol list {bright(path)} did not exist or was not a file")
    return path.read_text(encoding='utf-8')


def print_diff(lib: Path, consumer: Path, used: list[str], unused: list[str], missing: list[str]):
    print(rf'diffing symbols exported by {bright(lib)} against those imported by {bright(consumer)}:')
    batches = (
        (used, rf'exported symbols {bright("imported", "GREEN")} by {bright(consumer)}:', bright("OK", 'GREEN')),
        (unused, rf'exported symbols {bright("unused", "YELLOW")} by {bright(consumer)}:', bright("--", 'YELLOW')),
        (missing, rf'imported symbols {bright("not exported", "RED")} by {bright(lib)}:', bright("??", 'RED')),
    )
    for symbols, header, prefix in batches:
        if not symbols:
            continue
        print(header)
        for symbol in symbols:
            print(rf'[{prefix}] {symbol}')
    summary = r'exported '
    summary += bright(rf'{len(used)} / {len(used) + len(missing)}', 'GREEN' if not missing else 'RED')
    summary += rf' expected symbols'
    if unused:
        summary += rf', with {bright(len(unused), "YELLOW")} unused'
    summary += rf' ({len(used) + len(unused)} total).'
    print(summary)


def print_check(lib: Path, list_path: Path, expected: list[str], missing: list[str], unexpected: list[str]):
    print(rf'checking symbols {bright(lib)} with those listed in {bright(list_path)}:')
    missing_set = set(missing)
    for symbol in expected:
        if symbol in missing_set:
            print(rf'[{bright("??", "RED")}] {symbol} - {bright("not found", "RED")}')
        else:
            print(rf'[{bright("OK", "GREEN")}] {symbol}')
    if unexpected:
        print(rf'exported symbols that were {bright("NOT", "RED")} on the list:')
    for symbol in unexpected:
        print(rf'[{bright("XX", "RED")}] {symbol}')
    summary = r'found '
    summary += bright(rf'{len(expected) - len(missing)} / {len(expected)}', 'GREEN' if not missing else 'RED')
    summary += rf' expected symbols'
    if unexpected:
        summary += rf' and {bright(len(unexpected), "RED")} unexpected ones'
    summary += rf'.'
    print(summary)


def main_impl(argv=None) -> int:
    args = parse_args(argv)

    if args.print_version:
        print(VERSION_STRING)
        return 0

    if args.where:
        print(paths.PACKAGE)
        return 0

    lib = find_library(args.lib)
    include = compile_patterns(args.include)
    exclude = compile_patterns(args.exclude)
    exported = filter_symbols(run_nm(lib, abi_symbols=args.abi_symbols), include, exclude)

    if args.diff is None and args.check is None:
        for symbol in exported:
            print(symbol)
        return 0

    result = 0

    if args.diff is not None:
        if not args.diff.is_file():
            raise Error(rf"expected binary {bright(args.diff)} did not exist or was not a file")
        imported = run_nm(args.diff, undefined_only=True, abi_symbols=args.abi_symbols)
        imported = filter_symbols(imported, include, exclude)
        used, unused, missing = diff_symbols(exported, imported)
        print_diff(lib, args.diff, used, unused, missing)
        if missing:
            result |= 1

    if args.check is not None:
        expected = make_symbol_list(read_check_file(args.check), comments=True, abi_symbols=args.abi_symbols)
        expected = filter_symbols(expected, include, exclude)
        if not expected:
            raise Error(rf"expected symbol list {bright(args.check)} was empty")
        missing, unexpected = check_symbols(exported, expected)
        print_check(lib, args.check, expected, missing, unexpected)
        if missing:
            result |= 1
        if unexpected:
            result |= 2

    return result


def main(argv=None):
    colorama.init()
    try:
        sys.exit(main_impl(argv))
    except SystemExit as exit:
        raise exit from None
    except (Error, argparse.ArgumentError) as err:
        error(err)
        sys.exit(-1)
    except BaseException as err:
        with StringIO() as buf:
            buf.write(
                f'\n{dim("*************", "red")}\n\n'
                'You appear to have triggered an internal bug!'
                f'\n{style("Please file an issue at github.com/marzer/check-symbols/issues")}'
                '\nMany thanks!'
                f'\n\n{dim("*************", "red")}\n\n'
            )
            misk.print_exception(err, include_type=True, include_traceback=True, skip_frames=1, logger=buf)
            buf.write(f'{dim("*************", "red")}\n')
            print(buf.getvalue(), file=sys.stderr)
        sys.exit(-1)


if __name__ == '__main__':
    main()
