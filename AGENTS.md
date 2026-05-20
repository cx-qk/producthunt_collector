# Repository Guidelines

## Project Structure & Module Organization

This repository currently contains one Python utility project:

- `producthunt_collector/`: Product Hunt collection tool.
- `producthunt_collector/fetch_producthunt.py`: main CLI implementation.
- `producthunt_collector/config.json`: default crawl settings such as topics, vote threshold, page size, and output prefix.
- `producthunt_collector/.env`: local secret config, ignored by git; never commit it.
- `producthunt_collector/data/YYYY-MM-DD/`: generated CSV/JSON output and `checkpoint.json`.
- `producthunt_collector/run_collector.bat`: Windows double-click launcher.
- `producthunt_collector/run_collector.command`: macOS double-click launcher.

There is no dedicated test directory yet. Add tests under `producthunt_collector/tests/` when behavior becomes more complex.

## Build, Test, and Development Commands

Run commands from `producthunt_collector/`.

```powershell
uv sync
```

Creates or updates the local virtual environment from `pyproject.toml` and `uv.lock`.

```powershell
uv run python fetch_producthunt.py
```

Runs the collector using `config.json` and resumes from today's checkpoint.

```powershell
uv run python fetch_producthunt.py --help
```

Shows all CLI overrides, including `--config`, `--topics`, `--min-votes`, and `--no-resume`.

```powershell
uv run python -m py_compile fetch_producthunt.py
```

Performs a lightweight syntax check.

## Coding Style & Naming Conventions

Use Python 3.10+ with standard library types and small, explicit functions. Keep four-space indentation, `snake_case` for functions and variables, and `UPPER_SNAKE_CASE` for constants. Prefer structured JSON parsing and dataclasses over ad hoc string handling. Keep comments focused on non-obvious API, checkpoint, and rate-limit behavior.

## Testing Guidelines

No formal test framework is configured yet. For now, verify changes with `py_compile` and `--help`. When adding tests, use `pytest`, name files `test_*.py`, and cover config loading, checkpoint resume, deduplication, output path generation, and rate-limit handling without calling the live Product Hunt API.

## Commit & Pull Request Guidelines

This directory is not currently a git repository, so no commit history conventions are available. Use concise imperative commit messages such as `Add Product Hunt checkpoint resume`. Pull requests should describe the changed behavior, list validation commands, and note whether Product Hunt API calls were made. Include screenshots only for launcher or file-output workflow changes.

## Security & Configuration Tips

Keep `PRODUCTHUNT_ACCESS_TOKEN` in `.env` only. Do not print tokens, paste them into docs, or commit generated data unless intentionally sharing sample output. Prefer changing `config.json` over editing source code for new crawl targets.
