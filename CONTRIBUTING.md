# Contributing

Thanks for your interest! This project is actively maintained. Bug reports,
feature requests, and pull requests are welcome.

## Development setup

```bash
git clone https://github.com/OscillateLabsLLC/ha-neon-hub
cd ha-neon-hub
uv sync
```

## Before opening a PR

```bash
uv run ruff check .
uv run ruff format .
uv run mypy
uv run pytest --cov
```

All four must pass; coverage must stay at or above 95%. If you have a real
Neon Hub available, also run the live check:

```bash
NEON_HUB_USERNAME=... NEON_HUB_PASSWORD=... uv run python test_integration.py
```

## Conventions

- Conventional commit messages (`feat:`, `fix:`, `docs:`, ...)
- Keep `quality_scale.yaml` accurate when behavior changes
- Update `strings.json` **and** `translations/en.json` together (custom
  integrations only read the latter at runtime); never put literal URLs in
  either (hassfest rejects them)
