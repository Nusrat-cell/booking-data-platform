-- Web analytics events in the shape of the GA4 BigQuery export (one row per event, nested
-- event_params). They are built from the synthetic visits and bookings, so the web analytics
-- side can be reconciled with the booking system. Tracking loss is planted on purpose:
-- about 7 percent of purchases never reach analytics (consent, ad blockers) and about 3
-- percent are sent twice (a thank-you page that is reloaded).
CREATE OR REPLACE MACRO ga4_param_s(k, v) AS
    {'key': k, 'value': {'string_value': v, 'int_value': NULL::BIGINT, 'float_value': NULL::DOUBLE, 'double_value': NULL::DOUBLE}};
CREATE OR REPLACE MACRO ga4_param_i(k, v) AS
    {'key': k, 'value': {'string_value': NULL::VARCHAR, 'int_value': v::BIGINT, 'float_value': NULL::DOUBLE, 'double_value': NULL::DOUBLE}};

CREATE OR REPLACE TABLE ga4_events AS
WITH visit AS (
    SELECT visitor_id, ts, channel,
           CAST(epoch(ts) AS BIGINT) AS session_id,
           CASE channel WHEN 'google_cpc' THEN 'google' WHEN 'meta_ads' THEN 'facebook' WHEN 'newsletter' THEN 'newsletter'
                        WHEN 'organic' THEN 'google' WHEN 'direct' THEN '(direct)' WHEN 'affiliate' THEN 'urlaubsguru' ELSE '(not set)' END AS source,
           CASE channel WHEN 'google_cpc' THEN 'cpc' WHEN 'meta_ads' THEN 'paid_social' WHEN 'newsletter' THEN 'email'
                        WHEN 'organic' THEN 'organic' WHEN 'direct' THEN '(none)' WHEN 'affiliate' THEN 'affiliate' ELSE '(not set)' END AS medium,
           hash(visitor_id || CAST(ts AS VARCHAR)) % 100 AS dice
    FROM stg_touchpoints
),
purchase_session AS (  -- the session a booking belongs to: the latest visit before it
    SELECT b.booking_id, b.visitor_id, b.booked_at, b.gross_eur, b.currency, b.persons, b.event_name,
           v.session_id, v.source, v.medium
    FROM fct_bookings b
    ASOF JOIN visit v ON v.visitor_id = b.visitor_id AND b.booked_at >= v.ts
    WHERE b.status = 'confirmed'
),
base AS (
    SELECT visitor_id AS user_pseudo_id, ts AS t, 'session_start' AS event_name, session_id, source, medium,
           NULL::VARCHAR AS transaction_id, NULL::DOUBLE AS revenue, NULL::VARCHAR AS item_name
    FROM visit
    UNION ALL
    SELECT visitor_id, ts + INTERVAL 5 SECOND, 'page_view', session_id, source, medium, NULL, NULL, NULL FROM visit
    UNION ALL
    SELECT visitor_id, ts + INTERVAL 90 SECOND, 'view_item', session_id, source, medium, NULL, NULL, NULL FROM visit WHERE dice < 25
    UNION ALL
    SELECT visitor_id, ts + INTERVAL 200 SECOND, 'begin_checkout', session_id, source, medium, NULL, NULL, NULL FROM visit WHERE dice < 6
    UNION ALL
    SELECT visitor_id, booked_at - INTERVAL 20 MINUTE, 'view_item', session_id, source, medium, NULL, NULL, event_name FROM purchase_session
    UNION ALL
    SELECT visitor_id, booked_at - INTERVAL 8 MINUTE, 'begin_checkout', session_id, source, medium, NULL, NULL, event_name FROM purchase_session
    UNION ALL
    SELECT visitor_id, booked_at, 'purchase', session_id, source, medium, booking_id, gross_eur * 1.08, event_name
    FROM purchase_session WHERE hash(booking_id) % 100 >= 7                       -- 7 percent lost
    UNION ALL
    SELECT visitor_id, booked_at + INTERVAL 40 SECOND, 'purchase', session_id, source, medium, booking_id, gross_eur * 1.08, event_name
    FROM purchase_session WHERE hash(booking_id) % 100 >= 7 AND hash(booking_id || 'dup') % 100 < 3   -- 3 percent twice
)
SELECT strftime(t, '%Y%m%d') AS event_date,
       CAST(epoch_us(t) AS BIGINT) AS event_timestamp,
       event_name,
       [ga4_param_i('ga_session_id', session_id),
        ga4_param_s('source', source),
        ga4_param_s('medium', medium),
        ga4_param_s('page_location', CASE event_name WHEN 'purchase' THEN 'https://www.example-travel.test/thank-you' ELSE 'https://www.example-travel.test/' END)
       ] AS event_params,
       user_pseudo_id,
       {'source': source, 'medium': medium, 'name': '(not set)'} AS traffic_source,
       {'transaction_id': transaction_id, 'purchase_revenue_in_usd': revenue} AS ecommerce,
       [{'item_name': item_name}] AS items
FROM base;
