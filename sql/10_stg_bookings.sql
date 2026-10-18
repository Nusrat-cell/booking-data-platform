-- Newest export of a booking wins (a cancel is exported again with a later timestamp).
-- Rows that break a rule go to stg_bookings_rejected with the reason, never silently dropped.
CREATE OR REPLACE TABLE stg_bookings_latest AS
SELECT booking_id, visitor_id, CAST(booked_at AS TIMESTAMP) AS booked_at, event_id,
       CAST(persons AS INTEGER) AS persons, CAST(nights AS INTEGER) AS nights, currency,
       CAST(gross_amount AS DOUBLE) AS gross_amount, CAST(hotel_cost_eur AS DOUBLE) AS hotel_cost_eur,
       CAST(ticket_cost_eur AS DOUBLE) AS ticket_cost_eur, status,
       CAST(exported_at AS TIMESTAMP) AS exported_at
FROM raw_bookings
QUALIFY ROW_NUMBER() OVER (PARTITION BY booking_id ORDER BY CAST(exported_at AS TIMESTAMP) DESC) = 1;

CREATE OR REPLACE TABLE stg_bookings_rejected AS
SELECT b.*, CASE WHEN e.event_id IS NULL THEN 'unknown event'
                 WHEN b.persons <= 0 THEN 'persons must be positive'
                 WHEN b.gross_amount <= 0 THEN 'amount must be positive' END AS reason
FROM stg_bookings_latest b LEFT JOIN raw_events e USING (event_id)
WHERE e.event_id IS NULL OR b.persons <= 0 OR b.gross_amount <= 0;

CREATE OR REPLACE TABLE stg_bookings AS
SELECT * FROM stg_bookings_latest
WHERE booking_id NOT IN (SELECT booking_id FROM stg_bookings_rejected);

CREATE OR REPLACE TABLE stg_touchpoints AS
SELECT visitor_id, CAST(ts AS TIMESTAMP) AS ts,
       COALESCE(NULLIF(channel, ''), 'unknown') AS channel, campaign
FROM raw_touchpoints
QUALIFY ROW_NUMBER() OVER (PARTITION BY visitor_id, ts, channel ORDER BY _loaded_at DESC) = 1;
