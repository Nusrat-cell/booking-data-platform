-- How many sessions reach each step of the booking funnel, per medium.
WITH s AS (
  SELECT
    CONCAT(user_pseudo_id, CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)) AS session_key,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'medium') AS medium,
    event_name
  FROM `{ga4_events}`
)
SELECT
  medium,
  COUNT(DISTINCT IF(event_name = 'session_start', session_key, NULL)) AS sessions,
  COUNT(DISTINCT IF(event_name = 'view_item', session_key, NULL)) AS viewed_item,
  COUNT(DISTINCT IF(event_name = 'begin_checkout', session_key, NULL)) AS began_checkout,
  COUNT(DISTINCT IF(event_name = 'purchase', session_key, NULL)) AS purchased
FROM s
GROUP BY medium
ORDER BY sessions DESC
