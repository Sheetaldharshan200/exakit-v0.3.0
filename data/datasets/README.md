# Bundled datasets

One folder per dataset. The kit discovers every folder here that holds a
`dataset.conf`; nothing in the code names a dataset.

```
data/datasets/<id>/
  dataset.conf            id, label, schema, markers, order (and flag, for a record written by an older kit)
  01_create_schema.sql    CREATE SCHEMA and the tables, one CREATE TABLE per CSV, columns in the CSV's order
  02_load_data.sql        optional: statements that run after the CSVs are uploaded (derived tables, indexes)
  03_verify_setup.sql     optional: a check per table; a row containing ,FAIL, marks the dataset as not ready
  data/<TABLE>.csv        one CSV per table, named after the table, with a header row
```

`dataset.conf` is `key=value` lines:

| Key | Meaning |
|---|---|
| `id` | the dataset's name in `exakit data-load <id>`, `EXAKIT_DATASETS` and the personas |
| `label` | what the menu shows |
| `schema` | the schema the tables land in (default: the id, upper-cased) |
| `markers` | the tables whose rows prove the dataset is loaded, comma-separated |
| `order` | the menu's order (lower first) |
| `flag` | only for a dataset an older kit recorded under its own manifest flag |

To add a dataset: create the folder with the files above, then (optionally)
name its id in a persona under `catalog/personas/` or in
`data.default_datasets` of `catalog/kit.json`. `tests/test_sample_data_schema.py`
checks every folder: each CSV has a CREATE TABLE with the same columns in the
same order, every table has a primary key, and the verification script
mentions every table.
