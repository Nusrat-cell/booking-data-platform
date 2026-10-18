-- Reconcile web analytics with the booking system: purchases GA4 saw (distinct transaction id)
-- against confirmed bookings, plus purchase events fired more than once.
WITH ga AS (
  SELECT
    event_date,
    COUNT(*) AS purchase_events,
    COUNT(DISTINCT ecommerce.transaction_id) AS ga4_transactions
  FROM `{ga4_events}`
  WHERE event_name = 'purchase'
  GROUP BY event_date
),
bk AS (
  SELECT FORMAT_DATE('%Y%m%d', booking_date) AS event_date, COUNT(*) AS bookings
  FROM `{fct_bookings}`
  WHERE status = 'confirmed'
  GROUP BY event_date
)
SELECT
  bk.event_date,
  bk.bookings,
  COALESCE(ga.ga4_transactions, 0) AS ga4_transactions,
  COALESCE(ga.purchase_events, 0) - COALESCE(ga.ga4_transactions, 0) AS double_fired,
  ROUND(1 - SAFE_DIVIDE(COALESCE(ga.ga4_transactions, 0), bk.bookings), 3) AS share_missing_in_ga4
FROM bk
LEFT JOIN ga USING (event_date)
ORDER BY bk.event_date
