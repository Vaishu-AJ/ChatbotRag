# OKF knowledge bundle

Add one Markdown file per curated concept. The YAML frontmatter must include a non-empty `type`; `title` and `aliases` are used for query routing. Use `status: draft` while preparing a concept, then mark it `stable` and add a human `verified` event after checking its facts against the listed sources.

The chatbot uses current, non-draft concepts when a question clearly names their title or alias. Questions without a strong OKF match continue through the uploaded-document RAG index.

Copy `concept-template.md.example` to a new `.md` file to get started. `index.md`, `log.md`, and the template example are not loaded as concepts.

## Read-only PostgreSQL lookups

An OKF concept can declare a `database` mapping in its YAML frontmatter. For fixed lookups, the
backend queries only the named schema/table, configured joins, and returned columns. A concept with
`nl_to_sql: true` instead supplies a routing hint: the model maps a question to a structured table,
column, and filter plan using the live public schema. Python validates the plan and builds a
parameterized `SELECT`; model-produced SQL is never executed. Results are limited to 50 rows and
queries run in a read-only transaction. Related crew tables are joined only through `crew_code`.
Set `DATABASE_URL` in the local `.env` file and use a PostgreSQL role with `SELECT` permission only.
Never put credentials in an OKF Markdown file. For example:

```yaml
database:
  schema: public
  table: customers
  search_columns: [full_name]
  return_columns: [full_name, customer_id, status]
  ignored_terms: [customer, record, details]
  limit: 8
```

The values above are examples; replace them with real table and column names after reviewing your
schema. A concept must be `stable` to route questions. Without a strong concept title or alias match,
the app continues to use uploaded-document RAG. The crew concepts use the schema-aware planner for
all public tables, including bank and payroll records, with crew-linked joins.
