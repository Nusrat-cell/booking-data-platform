CREATE OR REPLACE TABLE fct_bookings AS
SELECT b.booking_id, b.visitor_id, b.booked_at, CAST(b.booked_at AS DATE) AS booking_date,
       b.event_id, e.name AS event_name, e.kind AS event_kind, e.country,
       b.persons, b.nights, b.currency, b.gross_amount, fx.eur_per_unit, fx.fx_source,
       b.status,
       ROUND(b.gross_amount * fx.eur_per_unit, 2) AS gross_eur,
       CASE WHEN b.status = 'confirmed' THEN ROUND(b.gross_amount * fx.eur_per_unit, 2) ELSE 0 END AS net_revenue_eur,
       CASE WHEN b.status = 'confirmed' THEN b.hotel_cost_eur + b.ticket_cost_eur ELSE 0 END AS cost_eur
FROM stg_bookings b
JOIN raw_events e USING (event_id)
LEFT JOIN dim_fx_daily fx ON fx.day = CAST(b.booked_at AS DATE) AND fx.currency = b.currency;
