# Booking data platform

A small data platform for an event travel business (hotel plus ticket packages for theme parks,
musicals and festivals). Daily exports land as files, an Airflow DAG loads them into a DuckDB
warehouse, SQL models build bookings, marketing attribution and a monthly finance report, a
quality gate stops the run when the numbers do not add up, and a small agent answers questions
about the warehouse with SQL.

I built it to practise the work of a junior data and AI engineer on a booking platform: keep the
pipelines running, keep the warehouse correct, give marketing and finance numbers they can trust,
and automate the repetitive questions. All data is synthetic.

```
landing files (per day)         raw tables            models                       marts
bookings.csv     \                         /-> stg_bookings (+ rejected) \
touchpoints.csv   +-> load_raw (per day) -+-> stg_touchpoints            +-> fct_bookings -> mart_finance_monthly
ad_spend.csv     /                         \-> dim_fx_daily             /        |
fx_rates.csv    /                                                      fct_attribution -> mart_marketing_daily
                                                                                  \-> mart_attribution_compare
Airflow: extract >> load_raw >> build_models >> quality_gate >> finance_report (+ Parquet export)
```

## Run it

```bash
pip install -r requirements.txt
python -m bookings backfill 2026-06-01 2026-10-17   # load 4.5 months, build models, show the gate
python -m pytest -q                                  # 37 tests, about 15 seconds
python -m agent.ops_agent "Which channel has the best ROAS?"   # needs ANTHROPIC_API_KEY
```

The DAG is in `dags/daily_bookings.py`. With Airflow 3.1 installed:

```bash
export AIRFLOW__CORE__DAGS_FOLDER=$PWD/dags
airflow db migrate && airflow dags reserialize
airflow dags test daily_bookings 2026-10-10
```

## What the pipeline does

* **Load by day, safe to retry.** Re-loading a day replaces that day, so a retry never doubles
  the numbers.
* **Newest export wins.** A booking that is cancelled later is exported again with a later time
  and replaces the confirmed line. Identical copies of a line collapse into one.
* **Nothing disappears silently.** Bookings for an unknown event or with zero persons go to
  `stg_bookings_rejected` with a reason. A check proves that every booking is either loaded or
  rejected.
* **Exchange rates.** Days without a published rate use the last published one, and each booking
  says whether its rate was published or carried forward. The finance report counts how many
  bookings rest on a carried rate.
* **Attribution.** Each confirmed booking is credited to a channel from the visits of the same
  person in the 30 days before it, as last touch and as first touch.
* **Quality gate.** Five blocking checks (one row per booking, every booking has a rate, revenue
  reconciles to the source, one attribution row per booking, loaded plus rejected equals
  received) and three warnings. A blocking failure fails the DAG run, so the finance report is
  never built from numbers that do not reconcile.

## What the numbers say

On the synthetic backfill (1 June to 17 October 2026, about 6,800 bookings):

| Channel | First touch bookings | Last touch bookings |
|-|-|-|
| google_cpc | 1,922 | 1,932 |
| organic | 1,288 | 1,110 |
| meta_ads | 1,192 | 830 |
| newsletter | 1,000 | 1,378 |
| direct | 922 | 1,117 |
| affiliate | 332 | 288 |

Under last touch, paid social looks about 30 percent weaker than it is at starting journeys, and
the newsletter looks about 38 percent stronger than it is at starting them: it closes bookings
that other channels opened. The newsletter ROAS (about 95) comes from a very small spend, so it
should not be used to move budget. The generator creates these patterns, so they are not
findings about a real business. They show that the model can tell the two views apart.

## The agent

`agent/ops_agent.py` uses the Anthropic Messages API with tool use. The model can call
`list_tables` and `run_sql`. The code runs the tool and sends the result back until the model
answers. The model has no write path: a query must be one SELECT, the connection is read-only,
and results are capped at 100 rows. A SQL error goes back to the model as text so it can correct
its query.

The tests use a fake client that plays the model, so they check the loop and the guard rails
(DROP, DELETE, UPDATE, COPY, ATTACH and two statements in one are all refused). I have not run
it against the live API in this repo, so the quality of its answers is untested.

## What worked

* **Logic in plain functions, DAG as a thin wrapper.** I could test the pipeline without Airflow
  and still run the real DAG.
* **The quality gate found a real bug on its first run.** Bookings made after midnight on the
  last loaded day had no exchange rate, because I built the EUR rows from the days with a
  published rate and not from the full date range. `every_booking_has_fx` failed with 2 rows.
  The fix is in `sql/00_dim_fx_daily.sql`.
* **Planting problems on purpose.** Each planted fault (duplicate, cancel, unknown event, zero
  persons, missing channel, missing CHF rate) has a test that checks it ends up in the right
  place.
* **Running the DAG for real.** `airflow dags test` ran all five tasks and wrote the report and
  three Parquet files.

## What did not work first time

* **`ds` as a task argument.** Airflow reserves `ds` for its own context, so `load_raw(ds)`
  failed with "The key 'ds' in args is a part of kwargs and therefore reserved". The argument is
  now called `day`.
* **Naive start date.** Airflow 3 refuses a DAG whose `start_date` has no timezone. It is now UTC.
* **Failures looked like hangs.** `airflow dags test` seemed stuck. It was waiting out the
  5 minute retry delay of the failed task, and the real error was in the log.
* **DuckDB has one writer.** Two runs at once would fight over the file, so the DAG has
  `max_active_runs=1`. A real warehouse (BigQuery, Trino) would not need this.
* **A flat margin.** My first generator used fixed cost factors, so every month had the same
  margin. Costs now vary per booking.

## Not done, and not tested

* **Dashboards.** The marts are written as Parquet and a compose file starts Metabase on Postgres, but I have not built the dashboards yet.
* **Docker.** There is a `Dockerfile` for the pipeline and agent image. I could not build it,
  because there was no Docker daemon in my environment.
* **A real warehouse.** DuckDB stands in for BigQuery or Trino. The SQL is close to standard,
  but I did not run it on either.
* **GitHub Actions on Python 3.12.** I ran everything locally on Python 3.13.

## Web analytics, BigQuery and Metabase

Web analytics events are built in the shape of the **GA4 BigQuery export** (one row per event,
nested `event_params`, `user_pseudo_id`, `ecommerce.transaction_id`), from the same synthetic visits and
bookings. Tracking loss is planted on purpose: about 7 percent of purchases never reach analytics and
about 3 percent are sent twice. Three queries, written in BigQuery Standard SQL, answer the questions
a marketing team asks:

| Query | Question |
|-|-|
| `ga4/bigquery/sessions_by_medium.sql` | Sessions per day, source and medium |
| `ga4/bigquery/funnel_by_medium.sql` | How many sessions reach view item, checkout and purchase, per medium |
| `ga4/bigquery/purchases_vs_bookings.sql` | GA4 purchases against confirmed bookings: missing and double-fired |

```bash
python -m bookings ga4        # 758,419 events; GA4 saw 6,226 of 6,657 bookings; 162 purchases sent twice
```

The queries run locally: sqlglot translates them from BigQuery to DuckDB, and the tests run them on the
synthetic export. The reconciliation finds the planted loss (about 6.5 percent missing).

For the real services:

```bash
# BigQuery (free sandbox, no billing)
pip install -r requirements-cloud.txt && gcloud auth application-default login
export GCP_PROJECT=your-project-id && python bigquery/load.py

# Metabase on Postgres
docker compose up -d db metabase
docker compose --profile load run --rm loader      # copies the marts into Postgres
# then open http://localhost:3000 and add the database: host db, user/password/database warehouse
```

| Part | Status |
|-|-|
| GA4 shaped events and the three queries | built, tested (8 tests) |
| BigQuery queries translated and run on DuckDB | tested |
| `bigquery/load.py` against real BigQuery | written, not run yet |
| `docker compose` file validated with `docker compose config` | validated only |
| Metabase dashboards, Postgres loader, Docker image | written, not run yet |

I will update this table when I have run the last three rows.

## Layout

```
bookings/     generator, pipeline functions, GA4 events, CLI
ga4/          BigQuery SQL on GA4 shaped events
bigquery/     loader for real BigQuery
scripts/      marts to Postgres for Metabase
sql/          the models, run in file order
dags/         the Airflow DAG
agent/        the SQL agent and its guard rails
tests/        37 tests: pipeline, agent, DAG shape, GA4 events
```
