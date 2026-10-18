-- Sessions per day and source / medium, from the GA4 export. Runs in BigQuery; the tests
-- translate it to DuckDB and run it on the synthetic export.
SELECT
  event_date,
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'source') AS source,
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'medium') AS medium,
  COUNT(DISTINCT CONCAT(user_pseudo_id, CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))) AS sessions
FROM `{ga4_events}`
WHERE event_name = 'session_start'
GROUP BY event_date, source, medium
ORDER BY event_date, sessions DESC
