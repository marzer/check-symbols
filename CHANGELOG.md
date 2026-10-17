# Changelog

## v0.3.2 - 2026-10-18

- fixed GCC's LTO causing function-local entities to leak into the symbol list

## v0.3.1 - 2026-10-15

- fixed weak and unique definition (V, W and u) regression

## v0.3.0 - 2026-10-15

- fixed `--diff` counting the consumer's own unique globals (u) as imports
- fixed some function templates being listed as `X::$typeinfo`, `X::$vtable` or `X::$VTT`
- ignored compiler-generated ABI symbols by default
- added symbol types R, and i
- added `--abi-symbols`

## v0.2.0 - 2026-10-15

- fixed versioned symbols (`foo@@VER`) keeping a trailing `@`, which also stopped their parameter lists being removed
- fixed soname version tags (`foo@@libfoo-1.0.so.0`) not being removed
- fixed `operator new`, `operator delete` and conversion operators being listed as `new`, `delete` and the target type
- fixed `operator()` names changing when read back from a check file
- fixed conversion operators to function and member function pointer types changing when read back from a check file
- fixed `typeinfo name for X` being normalised to `name for X::$typeinfo` (it is now `X::$typeinfo_name`)
- fixed names containing `#` (e.g. lambdas) being cut short; comments are now only stripped from check files, and never inside braces, square brackets or parentheses
- fixed a crash on check-file lines with an unmatched `)`
- fixed a missing `nm` and invalid `--include`/`--exclude` patterns being reported as internal bugs
- fixed directory discovery picking an arbitrary `.so` file when there were several (it now takes the first in sorted order)
- improved speed on libraries with many symbols
- dropped support for Python 3.8

## v0.1.0 - 2024-06-14

- First public release 🎉
