CREATE OR REPLACE TABLE mart_marketing_daily AS
WITH credited AS (
    SELECT b.booking_date AS day, a.last_touch_channel AS channel,
           COUNT(*) AS bookings, SUM(b.net_revenue_eur) AS revenue_eur
    FROM fct_bookings b JOIN fct_attribution a USING (booking_id)
    GROUP BY ALL
), spend AS (
    SELECT CAST(day AS DATE) AS day, channel, SUM(CAST(spend_eur AS DOUBLE)) AS spend_eur
    FROM raw_ad_spend GROUP BY ALL
)
SELECT COALESCE(c.day, s.day) AS day, COALESCE(c.channel, s.channel) AS channel,
       COALESCE(c.bookings, 0) AS bookings, ROUND(COALESCE(c.revenue_eur, 0), 2) AS revenue_eur,
       ROUND(COALESCE(s.spend_eur, 0), 2) AS spend_eur,
       ROUND(c.revenue_eur / NULLIF(s.spend_eur, 0), 2) AS roas,
       ROUND(s.spend_eur / NULLIF(c.bookings, 0), 2) AS cost_per_booking
FROM credited c FULL OUTER JOIN spend s ON c.day = s.day AND c.channel = s.channel;

CREATE OR REPLACE TABLE mart_attribution_compare AS
SELECT channel, SUM(first_touch) AS first_touch_bookings, SUM(last_touch) AS last_touch_bookings
FROM (
    SELECT first_touch_channel AS channel, 1 AS first_touch, 0 AS last_touch FROM fct_attribution
    UNION ALL
    SELECT last_touch_channel, 0, 1 FROM fct_attribution
) GROUP BY channel;
