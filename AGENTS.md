# Agent instructions

## Layout

```
src/extractor/   # application code (package name: extractor)
tests/           # pytest modules
ui/              # demo web app (Phase 2)
```

## Python

Use the existing conda environment **`voyfai`**.

```bash
conda activate voyfai
conda run -n voyfai <command>
```

## Dependencies

Declare packages in **`pyproject.toml`**. Install into **`voyfai`** with **`uv pip`**:

```bash
cd extractor
conda run -n voyfai uv pip install -e .
conda run -n voyfai uv pip install -e ".[dev]"
```

## Imports

Use **absolute imports** only. The installable package name is **`extractor`**.

```python
from extractor.module import thing
```

## Logging

Use **`extractor.logger`** for all application logging.

## Tests

Use **`pytest`**.

```bash
conda run -n voyfai pytest -q
conda run -n voyfai pytest -q -m integration
```
