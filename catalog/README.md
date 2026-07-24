# AskAmerica Data Catalog (MkDocs)

Published at https://askamerica.ai/catalog/ — a browsable schema / table / column
data dictionary generated from the govdata `*-schema.yaml` files.

## Build

```bash
python3 -m venv .venv && ./.venv/bin/python -m pip install mkdocs mkdocs-material
GOVDATA_RESOURCES=/path/to/calcite/govdata/src/main/resources ./.venv/bin/python gen_docs.py
./.venv/bin/mkdocs build          # -> site/
```

`gen_docs.py` writes `docs/`, `mkdocs.yml` (both generated). Deploy `site/` to the
`askamerica` Cloudflare Pages project under `/catalog` (bundled with the main web deploy).
