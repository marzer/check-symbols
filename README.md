# check-symbols

Command-line utility for checking ELF symbols.

It lists the dynamic symbols exported by a shared library, checks them against a list of expected symbols, or
compares them with the symbols an executable or another library imports. Symbol names are demangled and normalised
before they are printed or compared.

## Requirements

-   Linux, or another platform that uses ELF binaries
-   GNU nm (part of binutils) on the PATH
-   Python 3.9 or higher

## Installation

```
pip3 install check-symbols
```

## Usage

`check-symbols` is a command-line application:

```
usage: check-symbols [-h] [--version] [--check <path>] [--diff <path>] [--include <regex> [<regex> ...]]
                     [--exclude <regex> [<regex> ...]] [--abi-symbols]
                     [<path>]

Command-line utility for checking ELF symbols.

positional arguments:
  <path>                path to the shared library, or a directory containing it (default: discover automatically)

options:
  -h, --help            show this help message and exit
  --version             print the version and exit
  --check <path>        path to a text file containing a list of expected symbols (one per line). use a dash ('-') to
                        read from stdin.
  --diff <path>         compiled executable or shared library expected to consume the symbols
  --include <regex> [<regex> ...]
                        one or more regular expressions to select the listed/checked symbols.
  --exclude <regex> [<regex> ...]
                        one or more regular expressions to exclude from the listed/checked symbols.
  --abi-symbols         include compiler-generated ABI symbols such as vtables, typeinfo, thunks and guard variables

v0.2.0 - github.com/marzer/check-symbols
```

With neither --check nor --diff, the exported symbols are printed one per line. This output is valid input for
--check, so `check-symbols libfoo.so > symbols.txt` makes a first check file.

When the path is a directory, the first `.so` file in it (in sorted order) is used. Without a path, the current
directory is searched.

--check compares the exported symbols with a check file. --diff compares them with the undefined symbols of an
executable or another shared library. Every import that the library does not export counts as missing, including
imports from other libraries such as libc. A diff is therefore usually narrowed with --include or --exclude. Both
modes can be used in one run.

--include keeps the symbols that match every pattern, and --exclude drops the symbols that match any pattern. They
apply to both sides of a check or diff. Both options take one or more values, so give the library path before them,
or end the patterns with `--`.

### Check files

A check file holds one symbol per line, in the form that list mode prints. Blank lines are ignored. Comments start
with `#`, `;` or `//` and run to the end of the line. A marker inside braces, square brackets or parentheses, such as
the `#` in `{lambda(int)#1}` or the `;` in `[u8; 16]`, does not start a comment.

Lines in a check file are normalised in the same way as the library's symbols, so `ns::foo(int) const` matches
`ns::foo`.

Without --abi-symbols, lines for compiler-generated ABI symbols are ignored and never reported as missing. This
includes the forms that earlier versions printed, such as `X::$vtable`. To check these symbols, use --abi-symbols.

### Normalisation

Symbols are read with `nm -PBDCg`, which prints the demangled dynamic symbols, and are then normalised:

-   A library exports the symbols of type B and D (data), R (read-only data), T (code) and i (indirect functions).
    Types are matched case-sensitively. Weak and unique definitions (V, W and u) are dropped: they are mostly
    template instantiations and inline functions, and which of them appear depends on the toolchain. U, v and w are
    imports, and only U counts on the consumer side of --diff. A, the version definitions, is dropped, as are
    linker-generated symbols such as `_edata` and `__bss_start`.
-   Compiler-generated ABI symbols are dropped: vtables, VTTs, typeinfo, thunks, guard variables, TLS init and
    wrapper functions, transaction clones, reference temporaries, template parameter objects and module
    initialisers. Where these appear depends on LTO and the toolchain. --abi-symbols keeps them, weak or not.
-   Version tags are removed: `adler32@@ZLIB_1.2.0` becomes `adler32`.
-   Parameter lists and cv- and ref-qualifiers are removed, so all overloads of a function share one name:
    `ns::vec::get(int) const` becomes `ns::vec::get`.
-   nm prints return types only for function templates. Everything before the first space outside brackets is
    removed, so `int ns::vec::get<int>(int)` becomes `ns::vec::get<int>` and `unsigned int ns::vec::size<int>()`
    becomes `int ns::vec::size<int>`.
-   Operators keep their names: `ns::vec::operator new`, `ns::vec::operator()`, `ns::operator<<`. Conversion
    operators keep their target type: `ns::vec::operator bool`.
-   Lambdas and other local entities keep the name and parameter list of the enclosing function:
    `ns::foo()::{lambda(int)#1}::operator()`.
-   Common standard library types are shortened, and the `[abi:cxx11]` tag is removed (other ABI tags are kept):
    `std::basic_string<char, std::char_traits<char>, std::allocator<char> >` becomes `std::string`.
-   With --abi-symbols, vtables, typeinfo objects, typeinfo names and VTTs become `X::$vtable`, `X::$typeinfo`,
    `X::$typeinfo_name` and `X::$VTT`.
-   The list is sorted, and duplicates are removed.

### Exit codes

| Mode      | Value | Meaning                                                                               |
| :-------- | :---- | :------------------------------------------------------------------------------------ |
| _any_     | 0     | No issues were found                                                                  |
| `--check` | 1     | Some expected symbols listed in the check file were missing from the shared library   |
| `--check` | 2     | Some unexpected symbols not listed in the check file were found in the shared library |
| `--check` | 3     | Both of the above                                                                     |
| `--diff`  | 1     | Some symbols imported by the target binary were missing from the shared library       |
| _any_     | 255   | A fatal error occurred                                                                |

Values 1 and 2 are bit flags. When --check and --diff are used together, their results are combined, so a missing
symbol in either mode sets bit 1.

On invalid command-line arguments, argparse exits with 2. A script cannot tell this apart from bit 2 by the exit
code alone.

## Contributing

See [CONTRIBUTING.md](https://github.com/marzer/check-symbols/blob/main/CONTRIBUTING.md).
