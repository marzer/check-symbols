# check-symbols

Command-line utility for checking ELF symbols.

## Installation

`check-symbols` requires Python 3.8 or higher.

```
pip3 install check-symbols
```

## Usage

`check-symbols` is a command-line application

```
usage: check-symbols [-h] [--version] [--check <path>] [--diff <path>]
                     [--include <regex> [<regex> ...]] [--exclude <regex> [<regex> ...]] [<path>]

Exported symbol helper tool for shared library projects

positional arguments:
  <path>                path to the shared library, or a directory containing it (default: discover automatically)

options:
  -h, --help            show this help message and exit
  --version             print the version and exit
  --check <path>        path to a text file containing a list of expected symbols (one per line).
                        use a dash ('-') to read from stdin.
  --diff <path>         compiled executable or shared library expected to consume the symbols
  --include <regex> [<regex> ...]
                        one or more regular expressions to select the listed/checked symbols.
  --exclude <regex> [<regex> ...]
                        one or more regular expressions to exclude from the listed/checked symbols.

v0.1.0 - github.com/marzer/check-symbols
```

### Exit codes

| Mode      | Value | Meaning                                                                                  |
| :-------- | :---- | :--------------------------------------------------------------------------------------- |
| _any_     | -1    | A fatal error occurred                                                                   |
| _any_     | 0     | No issues were found                                                                     |
| `--check` | 1     | Some expected symbols listed in the check file were missing from the shared library      |
| `--check` | 2     | Some unexpected symbols not listed in the check file were found in the shared library    |
| `--check` | 3     | Both of the above                                                                        |
| `--diff`  | 1     | Some expected symbols imported by the target binary were missing from the shared library |
