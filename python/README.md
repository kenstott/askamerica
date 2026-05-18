# AskAmerica

Query 17 US government datasets — SEC filings, FEC campaign finance, Census, weather, energy, crime, and more — with a single line of Python.

## Install

```bash
pip install 'askamerica[engine]'
askamerica login            # get your free API key
```

The query engine JAR (~80 MB) is downloaded automatically on first use. To pre-download it explicitly (useful for CI or Docker):

```bash
askamerica install-engine   # optional — runs automatically on first query otherwise
```

## Query

**One-liner — returns a pandas DataFrame:**

```python
import askamerica as aa

df = aa.query("SELECT company_name, value_dollars FROM sec.financial_facts WHERE canonical_name = 'Revenue' ORDER BY value_dollars DESC FETCH FIRST 10 ROWS ONLY")
print(df)
```

**Raw JDBC connection:**

```python
import askamerica as aa

conn = aa.connect()
stmt = conn.createStatement()
rs = stmt.executeQuery("SELECT cik, company_name FROM sec.filing_metadata ORDER BY filing_date DESC FETCH FIRST 5 ROWS ONLY")
while rs.next():
    print(rs.getString("company_name"))
conn.close()
```

## Claude Desktop (MCP)

```bash
pip install 'askamerica[mcp]'
askamerica install-engine
askamerica mcp-config       # writes Claude Desktop config snippet
```

Sign up for a free API key at [askamerica.ai](https://askamerica.ai).
