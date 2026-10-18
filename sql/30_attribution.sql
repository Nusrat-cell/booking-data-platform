-- Every booking is credited to a channel by the visits of the same person in the 30 days
-- before the booking: last touch (the final nudge) and first touch (what brought them in).
CREATE OR REPLACE TABLE fct_attribution AS
WITH touches AS (
    SELECT b.booking_id, t.channel,
           ROW_NUMBER() OVER (PARTITION BY b.booking_id ORDER BY t.ts DESC) AS from_last,
           ROW_NUMBER() OVER (PARTITION BY b.booking_id ORDER BY t.ts ASC)  AS from_first
    FROM fct_bookings b
    JOIN stg_touchpoints t
      ON t.visitor_id = b.visitor_id AND t.ts <= b.booked_at AND t.ts >= b.booked_at - INTERVAL 30 DAY
    WHERE b.status = 'confirmed'
)
SELECT f.booking_id,
       MAX(CASE WHEN from_last = 1 THEN channel END)  AS last_touch_channel,
       MAX(CASE WHEN from_first = 1 THEN channel END) AS first_touch_channel,
       COUNT(*) AS touches
FROM touches f GROUP BY f.booking_id;
