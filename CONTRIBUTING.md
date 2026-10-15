# Contributing to check-symbols

Firstly: thanks! Any help is greatly appreciated.

For most situations the easiest way for you to contribute is to simply let me know what's going on by
[reporting an issue or requesting a feature][issues].

If you'd like to contribute more directly via a pull request, see below.

- [Pull Requests](#pull-requests)
	- [Getting started](#getting-started)
	- [Running the tests](#running-the-tests)
	- [Code style](#code-style)
	- [Versioning and releases](#versioning-and-releases)

## Pull Requests

### Getting started

A prerequisite of working on check-symbols with the intention of making a pull request is to have it installed
as 'editable' from a clone of the repository, with the pre-commit hooks enabled:

```sh
git clone <your check-symbols fork>
cd check-symbols
pip install -e '.[dev]'
pre-commit install
```

The `[dev]` extra pulls in pytest, ruff, pyright and pre-commit (matching the versions CI uses).

### Running the tests

```sh
pytest
```

There are two kinds of test:

-   Unit tests ([tests/test_units.py]) cover the symbol normalisation and the other pure helpers. They need no
    external tools and run in a fraction of a second.
-   CLI tests ([tests/test_cli.py]) build a small shared library and an executable that uses it from the sources in
    tests/sources, then run check-symbols on them. These need a C++ compiler (`c++`) and GNU nm on your PATH, and
    are skipped if either is missing.

The tests import check-symbols from the src directory of the checkout, so they test your changes even when another
copy is installed. CI runs them on every supported Python version.

### Code style

It's Python. I'm primarily a C++ programmer. I really don't care that much.

The codebase is linted and formatted with [ruff] and type-checked with [pyright] (config for both in
`pyproject.toml`). The pre-commit hooks run ruff on every commit, and CI runs both. Before pushing:

```sh
pre-commit run --all-files
pyright
```

I'm not too fussy though. I'm unlikely to reject a PR on the basis of style unless you do something truly horrendous.

### Versioning and releases

The version is stored in a single place: the `VERSION` file at the repo root, a bare `major.minor.patch` triplet.
setuptools reads it at build time, and at runtime check-symbols reads it back from the same file (falling back to
the installed package metadata when running from a wheel rather than a checkout).

Releases are automated and maintainer-only. Bumping `VERSION` on `main` is what cuts a release: CI tags
`v<version>`, and that tag triggers the publish workflow that uploads to PyPI.

The practical upshot for a PR: **don't touch `VERSION`**. I bump it myself when cutting a release, so a PR that also
bumps it just invites a merge conflict or an accidental publish. User-visible changes go under the Unreleased
heading at the top of `CHANGELOG.md`; please don't add a release heading.

<br /><br />

[issues]: https://github.com/marzer/check-symbols/issues
[ruff]: https://docs.astral.sh/ruff/
[pyright]: https://github.com/microsoft/pyright
[tests/test_units.py]: https://github.com/marzer/check-symbols/blob/main/tests/test_units.py
[tests/test_cli.py]: https://github.com/marzer/check-symbols/blob/main/tests/test_cli.py
