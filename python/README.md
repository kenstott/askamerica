# AskAmerica

Query US government data with a single line of Python.

```python
pip install askamerica
```

```python
import askamerica

askamerica.configure(api_key="aa_free_...")
df = askamerica.query("SELECT * FROM sec.filings WHERE year = 2024 LIMIT 100")
```

Sign up for a free API key at [askamerica.ai](https://askamerica.ai).
