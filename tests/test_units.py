#!/usr/bin/env python3
# This file is a part of marzer/check-symbols and is subject to the terms of the MIT license.
# Copyright (c) Mark Gillard <mark.gillard@outlook.com.au>
# See https://github.com/marzer/check-symbols/blob/main/LICENSE.txt for the full license text.
# SPDX-License-Identifier: MIT

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from check_symbols.main import (
    check_symbols,
    diff_symbols,
    filter_symbols,
    find_library,
    make_symbol_list,
    matches_all,
    matches_any,
    run_nm,
)
from check_symbols.version import VERSION, VERSION_STRING


def test_version_is_three_part_tuple_matching_string():
    assert isinstance(VERSION, tuple)
    assert len(VERSION) == 3
    assert all(isinstance(v, int) for v in VERSION)
    assert VERSION_STRING == '.'.join(str(v) for v in VERSION)


def test_version_file_on_disk_is_a_clean_triplet():
    raw = (Path(__file__).parents[1] / r'VERSION').read_text(encoding='utf-8')
    stripped = raw.strip()
    assert '\n' not in stripped
    parts = stripped.split('.')
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
    assert stripped == VERSION_STRING


@pytest.mark.parametrize(
    'packages,dist_info_beside,pyproject,expected',
    [
        ('deps', False, True, '9.8.7'),
        ('src', True, True, '9.8.7'),
        ('src', False, False, '9.8.7'),
        ('src', False, True, '3.2.0'),
    ],
    ids=['copy_outside_src', 'target_install_into_src', 'src_without_pyproject', 'source_tree'],
)
def test_the_version_file_is_read_only_from_a_source_tree(tmp_path, packages, dist_info_beside, pyproject, expected):
    host = tmp_path / 'host'
    shutil.copytree(
        Path(__file__).resolve().parents[1] / 'src' / 'check_symbols',
        host / packages / 'check_symbols',
        ignore=shutil.ignore_patterns('__pycache__'),
    )
    if pyproject:
        (host / 'pyproject.toml').write_text('', encoding='utf-8')
    (host / 'VERSION').write_text('3.2.0\n', encoding='utf-8')
    site = host / packages if dist_info_beside else tmp_path / 'site'
    metadata = site / 'check_symbols-9.8.7.dist-info' / 'METADATA'
    metadata.parent.mkdir(parents=True)
    metadata.write_text('Metadata-Version: 2.1\nName: check-symbols\nVersion: 9.8.7\n', encoding='utf-8')
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(host / packages), str(tmp_path / 'site')])}
    result = subprocess.run(
        [sys.executable, '-c', 'from check_symbols.version import VERSION_STRING; print(VERSION_STRING)'],
        capture_output=True,
        encoding='utf-8',
        check=False,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    'text,expected',
    [
        pytest.param('0000000000001130 T foo', ['foo'], id='address-and-category-removed'),
        pytest.param(
            '0000000000004010 B counter\n0000000000004008 D seed', ['counter', 'seed'], id='bss-and-data-kept'
        ),
        pytest.param('foo\nns::bar', ['foo', 'ns::bar'], id='bare-names-kept'),
        pytest.param('T b\nT a\nT b', ['a', 'b'], id='sorted-and-unique'),
        pytest.param('\n  \n   T   foo  \n\n', ['foo'], id='blank-lines-and-padding-dropped'),
        pytest.param('T foo(int)\nT foo(double)', ['foo'], id='overloads-merged'),
        pytest.param('T ns::Foo::bar(int) const', ['ns::Foo::bar'], id='member-function-qualifiers-removed'),
        pytest.param('T ns::Foo::bar() const volatile &&', ['ns::Foo::bar'], id='ref-qualifiers-removed'),
        pytest.param('T void ns::tmpl<int>(int)', ['ns::tmpl<int>'], id='template-return-type-removed'),
        pytest.param('T Foo const& ns::get<Foo>()', ['ns::get<Foo>'], id='const-reference-return-type-removed'),
        pytest.param('T std::pair<int, int> ns::make<int>(int)', ['ns::make<int>'], id='bracketed-return-type-removed'),
        pytest.param('T foo[abi:cxx11]()', ['foo'], id='abi-tag-removed'),
        pytest.param(
            'T std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >::size() const',
            ['std::string::size'],
            id='std-string-aliased',
        ),
        pytest.param(
            'T std::basic_ostringstream<wchar_t, std::char_traits<wchar_t>, std::allocator<wchar_t> >::str() const',
            ['std::wostringstream::str'],
            id='std-wostringstream-aliased',
        ),
        pytest.param(
            'T std::basic_ifstream<char, std::char_traits<char> >::close()',
            ['std::ifstream::close'],
            id='std-ifstream-aliased',
        ),
        pytest.param('D _edata\nB __bss_start\nB _end\nT _init\nT _fini', [], id='linker-symbols-dropped'),
        pytest.param(
            'B bss\nD data\nR rodata\nT text\nV weak_object\nW weak_function\nu unique\ni indirect',
            ['bss', 'data', 'indirect', 'rodata', 'text', 'unique', 'weak_function', 'weak_object'],
            id='exported-categories-kept',
        ),
        pytest.param(
            'U foo\nw bar\nv baz\nA FIXTURE_1.0\nN debug\nC common\nI alias\nb bss\nd data\nr rodata\nt text\n? unknown',
            [],
            id='other-categories-dropped',
        ),
    ],
)
def test_make_symbol_list_normalises(text, expected):
    assert make_symbol_list(text) == expected


def test_weak_definitions_are_kept_and_weak_imports_are_dropped():
    text = '0000000000001130 W foo\n0000000000004010 V bar\n                 w baz\n                 v qux'
    assert make_symbol_list(text) == ['bar', 'foo']


def test_undefined_only_keeps_imports_and_drops_exports():
    text = '                 U close@GLIBC_2.2.5\n0000000000001130 T foo'
    assert make_symbol_list(text, undefined_only=True) == ['close']


@pytest.mark.parametrize('category', list('ABCDGINRSTUVWbdinprstuvw?'))
def test_undefined_only_keeps_only_u(category):
    expected = ['foo'] if category == 'U' else []
    assert make_symbol_list(f'0000000000001130 {category} foo', undefined_only=True) == expected


ABI_SYMBOLS = [
    pytest.param('V', 'vtable for ns::Foo', 'ns::Foo::$vtable', id='vtable'),
    pytest.param('V', 'VTT for ns::Foo', 'ns::Foo::$VTT', id='vtt'),
    pytest.param(
        'V',
        'construction vtable for ns::Base-in-ns::Foo',
        'construction vtable for ns::Base-in-ns::Foo',
        id='construction-vtable',
    ),
    pytest.param('V', 'typeinfo for ns::Foo', 'ns::Foo::$typeinfo', id='typeinfo'),
    pytest.param('V', 'typeinfo name for ns::Foo', 'ns::Foo::$typeinfo_name', id='typeinfo-name'),
    pytest.param('D', 'typeinfo fn for ns::Foo', 'fn for ns::Foo::$typeinfo', id='typeinfo-fn'),
    pytest.param('u', 'guard variable for ns::f()::x', 'guard variable for ns::f()::x', id='guard-variable'),
    pytest.param('T', 'TLS init function for ns::x', 'TLS init function for ns::x', id='tls-init-function'),
    pytest.param('W', 'TLS wrapper function for ns::x', 'TLS wrapper function for ns::x', id='tls-wrapper-function'),
    pytest.param('W', 'virtual thunk to ns::Foo::~Foo()', 'thunk to ns::Foo::~Foo', id='virtual-thunk'),
    pytest.param('T', 'non-virtual thunk to ns::Foo::g(int)', 'thunk to ns::Foo::g', id='non-virtual-thunk'),
    pytest.param(
        'T', 'covariant return thunk to ns::Foo::clone() const', 'return thunk to ns::Foo::clone', id='covariant-thunk'
    ),
    pytest.param('T', 'transaction clone for ns::f(int)', 'clone for ns::f', id='transaction-clone'),
    pytest.param('B', 'reference temporary #0 for ns::r', 'reference temporary #0 for ns::r', id='reference-temporary'),
    pytest.param('R', '_ZGRN2ns1rE_', '_ZGRN2ns1rE_', id='undemangled-reference-temporary'),
    pytest.param(
        'V',
        'template parameter object for ns::point{3}',
        'template parameter object for ns::point{3}',
        id='template-parameter-object',
    ),
    pytest.param('T', 'initializer for module ns.mod', 'initializer for module ns.mod', id='module-initialiser'),
]


@pytest.mark.parametrize('category,name,normalised', ABI_SYMBOLS)
def test_abi_symbols_are_dropped_by_default(category, name, normalised):
    assert make_symbol_list(f'0000000000001130 {category} {name}') == []
    assert make_symbol_list(f'0000000000001130 {category} {name}@@LIB_1.0') == []
    assert make_symbol_list(f'                 U {name}', undefined_only=True) == []
    assert make_symbol_list(name, comments=True) == []


@pytest.mark.parametrize('category,name,normalised', ABI_SYMBOLS)
def test_abi_symbols_are_kept_with_the_flag(category, name, normalised):
    assert make_symbol_list(f'0000000000001130 {category} {name}', abi_symbols=True) == [normalised]
    assert make_symbol_list(f'0000000000001130 {category} {name}@@LIB_1.0', abi_symbols=True) == [normalised]
    assert make_symbol_list(f'                 U {name}', undefined_only=True, abi_symbols=True) == [normalised]


@pytest.mark.parametrize(
    'text,expected',
    [
        pytest.param('D vtable for Foo', ['Foo::$vtable'], id='vtable'),
        pytest.param('D typeinfo for Foo', ['Foo::$typeinfo'], id='typeinfo'),
        pytest.param('D VTT for Foo', ['Foo::$VTT'], id='vtt'),
        pytest.param('Foo :: $vtable', ['Foo::$vtable'], id='spaced-dollar-form'),
        pytest.param('[typeinfo] Foo', ['Foo::$typeinfo'], id='bracketed-form'),
    ],
)
def test_abi_symbols_normalise_to_dollar_names_with_the_flag(text, expected):
    assert make_symbol_list(text, abi_symbols=True) == expected


@pytest.mark.parametrize(
    'text,expected',
    [
        ('T vtable_for_x()', 'vtable_for_x'),
        ('T typeinfo::name()', 'typeinfo::name'),
        ('T typeinfo::vtable(int)', 'typeinfo::vtable'),
        ('B ns::VTT', 'ns::VTT'),
        ('T ns::guard_variable_for(int)', 'ns::guard_variable_for'),
        ('T ns::thunk::to(int)', 'ns::thunk::to'),
        ('u ns::f()::x', 'ns::f()::x'),
        ('W ns::f()::{lambda(int)#1}::operator()(int) const', 'ns::f()::{lambda(int)#1}::operator()'),
        ('T _ZGVbN2v_sin@@GLIBC_2.22', '_ZGVbN2v_sin'),
        ('T typeinfo ns::get<long>()', 'ns::get<long>'),
        ('W vtable ns::make<int>()', 'ns::make<int>'),
        ('W VTT ns::table<int>()', 'ns::table<int>'),
        ('W typeinfo const& ns::ref<int>()', 'ns::ref<int>'),
        ('W typeinfo name<int>()', 'name<int>'),
        ('W typeinfo for_each<int>()', 'for_each<int>'),
    ],
)
def test_user_declared_names_that_resemble_abi_symbols_are_kept(text, expected):
    assert make_symbol_list(text) == [expected]
    assert make_symbol_list(text, comments=True) == [expected]
    assert make_symbol_list(expected, comments=True) == [expected]


ABI_SYMBOLS_LISTED_BY_V0_2_0 = [
    'ns::Foo::$vtable',
    'ns::Foo::$VTT',
    'ns::Foo::$typeinfo',
    'ns::Foo::$typeinfo_name',
    'fn for ns::Foo::$typeinfo',
    'construction vtable for ns::Foo-in-ns::Foo<int>',
    'guard variable for ns::f()::{lambda()#1}::operator()() const::x',
    'TLS init function for ns::x',
    'TLS wrapper function for ns::x',
    'thunk to ns::Foo::f',
    'thunk to ns::Foo::operator()',
    'thunk to(anonymous namespace)::Foo::f',
    'return thunk to ns::Foo::clone',
    'clone for ns::f',
    'clone for ns::Foo::operator()',
    'clone for std::bad_exception::what',
    'thunk to std::strstream::~strstream',
    'reference temporary #0 for ns::x',
    '_ZGRN2ns1rE_',
    'template parameter object for ns::point{3}',
    'initializer for module foo.bar',
]

ABI_SYMBOLS_LISTED_BY_V0_1_0 = [
    'name for ns::Foo::$typeinfo',
    'name for ns::Foo@::$typeinfo',
    'fn for ns::Foo@::$typeinfo',
    'ns::Foo@::$vtable',
    'ns::Foo@::$VTT',
    'ns::Foo@@libfoo-1.0.so.0::$typeinfo',
    'for(anonymous namespace)::Foo::$vtable',
    'reference temporary',
    'vtable for ns::f()::{lambda',
    'variable for ns::f()::{lambda',
    'init function for ns::v<ns::f()::{lambda',
    'wrapper function for ns::v<ns::f()::{lambda',
    'parameter object for ns::wrap<ns::f()::{lambda',
    'virtual thunk to ns::f()::{unnamed type',
    'non-virtual thunk to ns::f()::{unnamed type',
    'covariant return thunk to ns::f()::{unnamed type',
    'transaction clone for ns::f()::{unnamed type',
    'virtual thunk to ns::Foo::f()@',
    'non-virtual thunk to ns::Foo::f()@',
    'covariant return thunk to ns::Foo::clone() const@',
    'transaction clone for ns::f(int)@',
    'transaction clone for std::bad_exception::what() const@',
    'virtual thunk to std::strstream::~strstream()@',
    'construction vtable for ns::Foo-in-ns::Foo<int>@',
    'guard variable for ns::x@',
    'TLS init function for ns::x@',
    'TLS wrapper function for ns::x@',
    'TLS wrapper function for(anonymous namespace)::x',
    'clone for(anonymous namespace)::Foo::f',
    'template parameter object for ns::point{3}@',
    'initializer for module foo.bar@',
    '_ZGRN2ns1rE_@',
]

ABI_SYMBOLS_WRITTEN_BY_HAND = [
    'vtable for ns::Foo',
    'typeinfo name for ns::Foo',
    'D vtable for ns::Foo',
    '[vtable] ns::Foo',
    'ns::Foo :: $typeinfo',
    'ns::Foo::$vtable # comment',
]


@pytest.mark.parametrize(
    'line', ABI_SYMBOLS_LISTED_BY_V0_2_0 + ABI_SYMBOLS_LISTED_BY_V0_1_0 + ABI_SYMBOLS_WRITTEN_BY_HAND
)
def test_abi_symbol_lines_in_a_check_file_are_ignored(line):
    assert make_symbol_list(line, comments=True) == []


@pytest.mark.parametrize(
    'line', ABI_SYMBOLS_LISTED_BY_V0_2_0 + ABI_SYMBOLS_LISTED_BY_V0_1_0 + ABI_SYMBOLS_WRITTEN_BY_HAND
)
def test_abi_symbol_lines_in_a_check_file_are_kept_with_the_flag(line):
    assert make_symbol_list(line, comments=True, abi_symbols=True) != []


def test_check_file_keeps_its_other_lines_when_abi_symbols_are_ignored():
    text = 'foo\nns::Foo::$vtable\nthunk to ns::Foo::f\nns::bar'
    assert make_symbol_list(text, comments=True) == ['foo', 'ns::bar']


@pytest.mark.parametrize(
    'name',
    [
        'Foo::$vtable',
        'Foo::$VTT',
        'Foo::$typeinfo',
        'Foo::$typeinfo_name',
        'construction vtable for ns::Foo-in-ns::Foo<int>',
        'guard variable for ns::f()::{lambda()#1}::operator()() const::x',
        'TLS wrapper function for ns::x',
        'thunk to ns::Foo::f',
        'return thunk to ns::Foo::clone',
        'clone for ns::f',
        '_ZGRN2ns1rE_',
    ],
)
def test_abi_symbol_names_are_unchanged_when_read_back_with_the_flag(name):
    assert make_symbol_list(name, comments=True, abi_symbols=True) == [name]


@pytest.mark.parametrize(
    'text,undefined_only,expected',
    [
        ('T adler32_combine@@ZLIB_1.2.2', False, 'adler32_combine'),
        ('T adler32_combine@ZLIB_1.2.2', False, 'adler32_combine'),
        ('adler32_combine@@ZLIB_1.2.2', False, 'adler32_combine'),
        ('T json_array_get_length@@libjson-glib-1.0.so.0', False, 'json_array_get_length'),
        ('U json_array_get_length@libjson-glib-1.0.so.0', True, 'json_array_get_length'),
        ('T tilde_answer@@libtilde-1.0~x.so', False, 'tilde_answer'),
        ('U tilde_answer@libtilde-1.0~x.so', True, 'tilde_answer'),
    ],
)
def test_version_tags_are_removed_completely(text, undefined_only, expected):
    assert make_symbol_list(text, undefined_only=undefined_only) == [expected]


@pytest.mark.parametrize(
    'text,expected',
    [
        ('T operator new(unsigned long)@@GLIBCXX_3.4', 'operator new'),
        ('T ns::Foo::bar(int) const@@LIB_1.0', 'ns::Foo::bar'),
        ('T void ns::tmpl<int>(int)@LIB_1.0', 'ns::tmpl<int>'),
        ('T ns::Foo::bar(int) const@@libfoo++-1.0.so.0', 'ns::Foo::bar'),
    ],
)
def test_versioned_functions_lose_their_signature(text, expected):
    assert make_symbol_list(text) == [expected]


@pytest.mark.parametrize(
    'text,expected',
    [
        ('T operator new(unsigned long)', 'operator new'),
        ('T operator new[](unsigned long)', 'operator new[]'),
        ('T operator delete(void*)', 'operator delete'),
        ('T operator delete[](void*, unsigned long)', 'operator delete[]'),
        ('T Foo::operator new(unsigned long)', 'Foo::operator new'),
        ('T Foo::operator delete(void*)', 'Foo::operator delete'),
    ],
)
def test_operator_new_and_delete_keep_their_names(text, expected):
    assert make_symbol_list(text) == [expected]


@pytest.mark.parametrize(
    'text,expected',
    [
        ('T Foo::operator bool() const', 'Foo::operator bool'),
        ('T Foo::operator unsigned long() const', 'Foo::operator unsigned long'),
        ('T Foo::operator void const*() const', 'Foo::operator void const*'),
        ('T Foo::operator Bar const&() const', 'Foo::operator Bar const&'),
        (
            'T Foo::operator std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >() const',
            'Foo::operator std::string',
        ),
        ('T Foo::operator void (*)(int)() const', 'Foo::operator void(*)(int)'),
        ('T Foo::operator void (Foo::*)() const() const@@LIB_1.0', 'Foo::operator void(Foo::*)() const'),
    ],
)
def test_conversion_operators_keep_their_class_and_target_type(text, expected):
    assert make_symbol_list(text) == [expected]


@pytest.mark.parametrize(
    'text,expected',
    [
        ('T ns::Foo::operator()(int) const', 'ns::Foo::operator()'),
        ('T ns::Foo::operator[](unsigned long)', 'ns::Foo::operator[]'),
        ('T ns::Foo::operator->() const', 'ns::Foo::operator->'),
        ('T ns::operator<(ns::Foo const&, ns::Foo const&)', 'ns::operator<'),
        ('T ns::operator<<(std::ostream&, ns::Foo const&)', 'ns::operator<<'),
        ('T operator"" _km(unsigned long long)', 'operator"" _km'),
        ('T bool ns::operator==<int>(ns::Foo<int> const&, ns::Foo<int> const&)', 'ns::operator==<int>'),
    ],
)
def test_symbolic_operators_keep_their_names(text, expected):
    assert make_symbol_list(text) == [expected]


@pytest.mark.parametrize(
    'text', ['typeinfo name for Foo', 'D typeinfo name for Foo', 'Foo :: $typeinfo_name', '[typeinfo_name] Foo']
)
def test_typeinfo_name_normalises_to_a_typeinfo_name_suffix(text):
    assert make_symbol_list(text, abi_symbols=True) == ['Foo::$typeinfo_name']


def test_lambda_names_in_nm_output_are_not_cut_at_the_hash():
    text = '0000000000001139 T foo()::{lambda(int)#1}::operator()(int) const'
    assert make_symbol_list(text) == ['foo()::{lambda(int)#1}::operator()']


def test_local_entities_keep_the_enclosing_function_parameter_list():
    text = '0000000000001139 T ns::f(int)::{lambda(void const*)#1}::_FUN(void const*)'
    assert make_symbol_list(text) == ['ns::f(int)::{lambda(void const*)#1}::_FUN']


def test_comment_markers_in_nm_output_are_kept(monkeypatch):
    name = '<std::net::ip_addr::Ipv6Addr as core::convert::From<[u8; 16]>>::from'
    stdout = f'0000000000001139 T {name}\n'
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout, ''))
    assert run_nm(Path('libfake.so')) == [name]


def test_run_nm_drops_abi_symbols_unless_asked(monkeypatch):
    stdout = '0000000000004d80 V vtable for Foo\n0000000000001139 T foo()\n'
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout, ''))
    assert run_nm(Path('libfake.so')) == ['foo']
    assert run_nm(Path('libfake.so'), abi_symbols=True) == ['Foo::$vtable', 'foo']


def test_check_file_comments_are_removed():
    text = '# header\nfoo # c\nfoo ; c\nbar // c\nbaz#c\n; another\n// and another'
    assert make_symbol_list(text, comments=True) == ['bar', 'baz', 'foo']


def test_check_file_comment_markers_inside_braces_are_kept():
    text = 'foo()::{lambda(int)#1}::operator() # c\nns::f()::{unnamed type#1}::g'
    expected = ['foo()::{lambda(int)#1}::operator()', 'ns::f()::{unnamed type#1}::g']
    assert make_symbol_list(text, comments=True) == expected


def test_check_file_comment_markers_inside_square_brackets_and_parentheses_are_kept():
    name = '<std::net::ip_addr::Ipv6Addr as core::convert::From<[u8; 16]>>::from'
    assert make_symbol_list(f'{name} # c', comments=True) == [name]
    assert make_symbol_list('ns::f(char#)::g ; c', comments=True) == ['ns::f(char#)::g']


def test_check_file_comments_after_a_stray_closing_bracket_are_removed():
    assert make_symbol_list('foo) # c\nbar] ; c\nbaz} // c', comments=True) == ['bar]', 'baz}', 'foo)']


@pytest.mark.parametrize(
    'text,expected', [(')', [')']), (') const', [') const']), ('foo(int)\n)', [')', 'foo']), ('foo)', ['foo)'])]
)
def test_unbalanced_parentheses_are_kept_without_crashing(text, expected):
    assert make_symbol_list(text, comments=True) == expected


@pytest.mark.parametrize(
    'name',
    [
        'foo',
        'ns::Foo::bar',
        'ns::tmpl<int>',
        'std::string::size',
        'operator new',
        'operator delete[]',
        'Foo::operator bool',
        'Foo::operator unsigned long',
        'Foo::operator Bar const&',
        'Foo::operator void(*)(int)',
        'Foo::operator void(&&)(int)',
        'Foo::operator void(* const)(int)',
        'Foo::operator void(*(*)(int))(char)',
        'Foo::operator void(Foo::*)() const',
        'std::__exception_ptr::exception_ptr::operator void(std::__exception_ptr::exception_ptr::*)()',
        'foo()::{lambda(int)#1}::operator void(*)(int)',
        'ns::Foo::operator()',
        'ns::Foo::operator()<int>',
        'ns::operator<<',
        'ns::operator==<int>',
        'foo()::{lambda(int)#1}::operator()',
        'ns::f(int)::{lambda(void const*)#1}::_FUN',
        '<std::net::ip_addr::Ipv6Addr as core::convert::From<[u8; 16]>>::from',
    ],
)
def test_normalised_names_are_unchanged_when_read_back_from_a_check_file(name):
    assert make_symbol_list(name, comments=True) == [name]


def test_call_operator_qualifiers_in_a_check_file_are_removed():
    assert make_symbol_list('ns::Foo::operator() const', comments=True) == ['ns::Foo::operator()']


def test_matches_all_requires_every_pattern():
    patterns = [re.compile(r'^foo'), re.compile(r'bar$')]
    assert matches_all('foo_bar', patterns)
    assert not matches_all('foo_baz', patterns)
    assert not matches_all('qux_bar', patterns)


def test_matches_all_passes_without_patterns():
    assert matches_all('foo', [])
    assert matches_all('foo', None)


def test_matches_any_requires_one_pattern():
    patterns = [re.compile(r'^foo'), re.compile(r'bar$')]
    assert matches_any('foo_baz', patterns)
    assert matches_any('qux_bar', patterns)
    assert not matches_any('qux_baz', patterns)


def test_matches_any_fails_without_patterns():
    assert not matches_any('foo', [])
    assert not matches_any('foo', None)


def test_filter_symbols_includes_all_and_excludes_any():
    symbols = ['a::x', 'a::y', 'a::z', 'b::x']
    include = [re.compile(r'^a::')]
    exclude = [re.compile(r'y$'), re.compile(r'z$')]
    assert filter_symbols(symbols, include, exclude) == ['a::x']


def test_diff_symbols_splits_used_unused_and_missing():
    assert diff_symbols(['a', 'b', 'c'], ['b', 'c', 'd']) == (['b', 'c'], ['a'], ['d'])


def test_check_symbols_splits_missing_and_unexpected():
    assert check_symbols(['a', 'b', 'c'], ['b', 'c', 'd']) == (['d'], ['a'])


def test_find_library_takes_the_first_library_in_sorted_order(tmp_path, monkeypatch):
    (tmp_path / 'a.so').mkdir()
    for name in ('b.so', 'c.so', 'd.so'):
        (tmp_path / name).touch()
    listing = [tmp_path / name for name in ('d.so', 'a.so', 'c.so', 'b.so')]
    monkeypatch.setattr(Path, 'iterdir', lambda self: iter(listing))
    assert find_library(tmp_path) == tmp_path / 'b.so'
