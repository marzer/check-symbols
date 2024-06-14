#!/usr/bin/env python3
# This file is a part of marzer/check-symbols and is subject to the the terms of the MIT license.
# Copyright (c) Mark Gillard <mark.gillard@outlook.com.au>
# See https://github.com/marzer/check-symbols/blob/main/LICENSE.txt for the full license text.
# SPDX-License-Identifier: MIT

import argparse
import re
import os
import subprocess
import sys
import misk
from io import StringIO
from pathlib import Path

import colorama

from . import paths
from .colour import *
from .version import *


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


def make_symbol_list(s, undefined_only=False):
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
    s = [re.sub(r'^(.*?)(?:[#;]|//).*$', r'\1', i) for i in s]
    # remove any categorized symbols we don't want (https://linux.die.net/man/1/nm)
    allowed_categories = (r'U',) if undefined_only else (r'B', r'D', r'T')
    s2 = []
    for i in s:
        m = re.match(r'^(?:[0-9a-fA-F]{6,32}\s+)?([a-zA-Z])\s+(.+?)$', i)
        if m:
            if not m[1].upper() in allowed_categories:
                continue
            i = m[2].strip()
        s2.append(i)
    s = s2
    # normalize spacing and weird oddities
    s = [re_sub_all(r'^(.+?)@\s*[a-zA-Z][a-zA-Z0-9._]*\s*$', r'\1', i) for i in s]  # @IMPORT tags
    s = [re_sub_all(r'>\s+>', '>>', i) for i in s]
    s = [re_sub_all(r',\s\s+([a-zA-Z0-9_])', r', \1', i) for i in s]
    s = [re_sub_all(r'([a-zA-Z0-9_>])\s+\(', r'\1(', i) for i in s]
    # normalize vtable and type info representations
    s = [re.sub(r'^\s*(.+?)\s*::\s*\$\s*(vtable|typeinfo|VTT)\s*$', r'\1::$\2', i).strip() for i in s]
    s = [re.sub(r'^\s*\[\s*(vtable|typeinfo|VTT)\s*\]\s*(.+?)$', r'\2::$\1', i).strip() for i in s]
    s = [re.sub(r'^\s*(vtable|typeinfo|VTT)\s+(?:for\s+)?(.+?)$', r'\2::$\1', i).strip() for i in s]
    # special handling for functions
    s2 = []
    for i in s:
        # find parameter list
        # (regex alone is not enough here - a parens-balancing reverse parse is required)
        m = re.search(r'\)(?:\s*(?:const|volatile|noexcept|&&?))*$', i)
        if m:
            parens = -1
            for pos in range(m.start() - 1, -1, -1):
                if i[pos] == '(':
                    parens += 1
                elif i[pos] == ')':
                    parens -= 1
                if parens == 0:
                    break
            # we found a parameter list, so chop it off
            if pos >= 0 and parens == 0 and i[pos] == '(':
                i = i[:pos].strip()
                # now lets see if we have a return type
                # again we need to do a bracket-balancing parse
                parens = 0  # ()
                square = 0  # []
                curly = 0  # {}
                angle = 0  # <>
                for pos in range(len(i)):
                    if i[pos] == '(':
                        parens += 1
                    elif i[pos] == ')':
                        parens -= 1
                    elif i[pos] == '[':
                        square += 1
                    elif i[pos] == ']':
                        square -= 1
                    elif i[pos] == '{':
                        curly += 1
                    elif i[pos] == '}':
                        curly -= 1
                    elif i[pos] == '<':
                        angle += 1
                    elif i[pos] == '>':
                        angle -= 1
                    elif i[pos] in (' ', '\t') and parens == 0 and square == 0 and curly == 0 and angle == 0:
                        i = i[pos:].strip()
                        break

                i = re_sub_all(r'^\s*(?:const|volatile|const\s+volatile|volatile\s+const)\s*&\s+(.+?)\s*$', r'\1', i)

        s2.append(i)
    s = s2
    # remove blank lines
    s = [i for i in [j.strip() for j in s] if i]
    # remove more implementation details
    s = [i for i in s if not re.fullmatch(r'(?:__bss_start|_edata|_end|_fini|_init)', i)]
    # de-duplicate and sort
    s = sorted(misk.remove_duplicates(s))
    return s


def get_relative_path(p: Path, relative_to: Path = Path.cwd()) -> Path:

    p = misk.coerce_path(p).resolve()
    relative_to = misk.coerce_path(relative_to).resolve()
    try:
        return Path(os.path.relpath(str(p), str(relative_to)))
    except:
        return p


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


def main_impl():
    args = argparse.ArgumentParser(
        description=r"Exported symbol helper tool for shared library projects",
        epilog=rf'v{VERSION_STRING} - github.com/marzer/check-symbols',
    )
    args.add_argument(r'--version', action=r'store_true', help=r"print the version and exit", dest=r'print_version')
    args.add_argument(r'--where', action=r'store_true', help=argparse.SUPPRESS)
    args.add_argument(
        r"lib",
        type=Path,
        nargs=r'?',
        default=None,
        metavar=r"<path>",
        help="path to the shared library, or a directory containing it (default: discover automatically)",
    ),
    args.add_argument(
        r"--check",
        type=Path,
        default=None,
        metavar=r"<path>",
        help='path to a text file containing a list of expected symbols (one per line). use a dash (\'-\') to read from stdin.',
    )
    args.add_argument(
        r"--diff",
        type=Path,
        default=None,
        metavar=r"<path>",
        help=rf"compiled executable or shared library expected to consume the symbols",
    )
    args.add_argument(
        r"--include",
        type=str,
        nargs='+',
        metavar=r"<regex>",
        help=rf"one or more regular expressions to select the listed/checked symbols.",
    )
    args.add_argument(
        r"--exclude",
        type=str,
        nargs='+',
        metavar=r"<regex>",
        help=rf"one or more regular expressions to exclude from the listed/checked symbols.",
    )
    args = args.parse_args()

    if args.print_version:
        print(VERSION_STRING)
        return

    if args.where:
        print(paths.PACKAGE)
        return

    # find lib
    if args.lib is None:
        args.lib = Path.cwd()
    if args.lib.is_dir():
        dir = args.lib
        args.lib = None
        for item in dir.iterdir():
            if item.name.endswith('.so') and item.is_file():
                args.lib = item
                break
        if args.lib is None:
            return rf"could not find a shared library in {bright(dir)}"
    else:
        if not args.lib.is_file():
            return rf"shared library {bright(args.lib)} did not exist or was not a file"

    # compute patterns
    if not args.include:
        args.include = []
    if not args.exclude:
        args.exclude = []
    args.include = [re.compile(s) for s in args.include]
    args.exclude = [re.compile(s) for s in args.exclude]

    def get_filtered_symbols_from_binary(bin_path, undefined_only=False):
        nonlocal args
        symbols = subprocess.run(
            [r'nm', r'-PBDCg', str(bin_path)], capture_output=True, cwd=str(Path.cwd()), encoding='utf-8'
        )
        if symbols.returncode != 0:
            outputs = ''
            if symbols.stdout:
                outputs += f'\n  {bright("stdout")}:\n'
                outputs += "\n".join([rf'    {i.strip()}' for i in symbols.stdout.split('\n') if i.strip()])
            if symbols.stderr:
                outputs += f'\n  {bright("stderr")}:\n'
                outputs += "\n".join([rf'    {i.strip()}' for i in symbols.stderr.split('\n') if i.strip()])
            return (False, rf"{bright('nm')} exited with code {bright(symbols.returncode)}{outputs}")
        symbols = make_symbol_list(symbols.stdout, undefined_only=undefined_only)
        symbols = [s for s in symbols if matches_all(s, args.include)]
        symbols = [s for s in symbols if not matches_any(s, args.exclude)]
        symbols = sorted(misk.remove_duplicates(symbols))
        return (True, symbols)

    # get symbols from target lib
    symbols = get_filtered_symbols_from_binary(args.lib)
    if not symbols[0]:
        return symbols[1]  # error message
    symbols = symbols[1]

    # just list the symbols and exit if not in 'diff' or 'check' mode
    if args.diff is None and args.check is None:
        for s in symbols:
            print(s)
        return 0

    retval = 0

    # diff against binary
    if args.diff is not None:
        if not (args.diff.exists() and args.diff.is_file()):
            return rf"expected binary {bright(args.diff)} did not exist or was not a file"
        exe_symbols = get_filtered_symbols_from_binary(args.diff, undefined_only=True)
        if not exe_symbols[0]:
            return exe_symbols[1]  # error message
        exe_symbols = exe_symbols[1]
        print(rf'diffing symbols exported by {bright(args.lib)} against those imported by {bright(args.diff)}:')
        unused = []
        used = []
        missing = []
        for symbol in symbols:
            (used if symbol in exe_symbols else unused).append(symbol)
        for symbol in exe_symbols:
            if symbol not in used:
                missing.append(symbol)
        batches = (
            (used, rf'exported symbols {bright("imported", "GREEN")} by {bright(args.diff)}:', bright("OK", 'GREEN')),
            (unused, rf'exported symbols {bright("unused", "YELLOW")} by {bright(args.diff)}:', bright("--", 'YELLOW')),
            (missing, rf'imported symbols {bright("not exported", "RED")} by {bright(args.lib)}:', bright("??", 'RED')),
        )
        for result, header, prefix in batches:
            if result:
                print(header)
                for symbol in result:
                    print(rf'[{prefix}] {symbol}')
        summary = r'exported '
        summary += bright(rf'{len(used)} / {len(used) + len(missing)}', 'GREEN' if not missing else 'RED')
        summary += rf' expected symbols'
        if len(unused):
            summary += rf', with {bright(len(unused), "YELLOW")} unused'
        summary += rf' ({len(symbols)} total).'
        print(summary)
        if missing:
            retval = retval or 1

    # check against list file
    if args.check is not None:
        check_text = ''
        if args.check == Path('-'):
            for line in sys.stdin:
                check_text += f'{line.rstrip()}\n'
        else:
            if not (args.check.exists() and args.check.is_file()):
                return rf"expected symbol list {bright(args.check)} did not exist or was not a file"
            check_text = misk.read_all_text_from_file(args.check)
        expected_symbols = make_symbol_list(check_text)
        expected_symbols = [s for s in expected_symbols if matches_all(s, args.include)]
        expected_symbols = [s for s in expected_symbols if not matches_any(s, args.exclude)]
        if not expected_symbols:
            return rf"expected symbol list {bright(args.check)} was empty"
        print(rf'checking symbols {bright(args.lib)} with those listed in {bright(args.check)}:')
        found_count = 0
        for symbol in expected_symbols:
            if symbol in symbols:
                print(rf'[{bright("OK", "GREEN")}] {symbol}')
                found_count += 1
            else:
                print(rf'[{bright("??", "RED")}] {symbol} - {bright("not found", "RED")}')
        unexpected_count = 0
        for symbol in symbols:
            if symbol not in expected_symbols:
                if unexpected_count == 0:
                    print(rf'exported symbols that were {bright("NOT", "RED")} on the list:')
                print(rf'[{bright("XX", "RED")}] {symbol}')
                unexpected_count += 1

        summary = r'found '
        summary += bright(
            rf'{found_count} / {len(expected_symbols)}', 'GREEN' if (found_count == len(expected_symbols)) else 'RED'
        )
        summary += rf' expected symbols'
        if unexpected_count:
            summary += rf' and {bright(unexpected_count, "RED")} unexpected ones'
        summary += rf'.'
        print(summary)

        if found_count != len(expected_symbols):
            retval = retval | 1
        if unexpected_count:
            retval = retval | 2

    return retval


def main():
    colorama.init()
    result = None
    try:
        result = main_impl()
        if result is None:
            sys.exit(0)
        elif isinstance(result, int):
            sys.exit(result)
        elif isinstance(result, str):  # error message
            error(result)
            sys.exit(-1)
        else:
            error('unexpected result type')
            sys.exit(-1)
    except SystemExit as exit:
        raise exit from None
    except argparse.ArgumentError as err:
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
