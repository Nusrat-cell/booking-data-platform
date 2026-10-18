-- The monthly finance report: what was booked, what was cancelled, what is left, and margin.
CREATE OR REPLACE TABLE mart_finance_monthly AS
SELECT strftime(booking_date, '%Y-%m') AS month,
       COUNT(*) AS bookings,
       COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled,
       ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'cancelled') / COUNT(*), 1) AS cancel_rate_pct,
       ROUND(SUM(gross_eur), 2) AS gross_booked_eur,
       ROUND(SUM(gross_eur) - SUM(net_revenue_eur), 2) AS cancelled_eur,
       ROUND(SUM(net_revenue_eur), 2) AS net_revenue_eur,
       ROUND(SUM(cost_eur), 2) AS cost_eur,
       ROUND(SUM(net_revenue_eur) - SUM(cost_eur), 2) AS gross_margin_eur,
       ROUND(100.0 * (SUM(net_revenue_eur) - SUM(cost_eur)) / NULLIF(SUM(net_revenue_eur), 0), 1) AS margin_pct,
       COUNT(*) FILTER (WHERE fx_source = 'carried') AS bookings_on_carried_fx
FROM fct_bookings GROUP BY 1 ORDER BY 1;
