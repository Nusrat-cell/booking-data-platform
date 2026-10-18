-- One rate per currency per day. Days without a published rate use the last published one,
-- and the row says so (fx_source), so a report can show how much rests on carried rates.
CREATE OR REPLACE TABLE dim_fx_daily AS
WITH spine AS (
    SELECT CAST(d AS DATE) AS day, c.currency
    FROM generate_series(
        (SELECT MIN(CAST(day AS DATE)) FROM raw_fx),
        (SELECT MAX(CAST(day AS DATE)) FROM raw_fx) + INTERVAL 1 DAY, INTERVAL 1 DAY) AS g(d)
    CROSS JOIN (SELECT DISTINCT currency FROM raw_fx) c
), published AS (
    SELECT CAST(day AS DATE) AS day, currency, CAST(eur_per_unit AS DOUBLE) AS eur_per_unit FROM raw_fx
)
SELECT s.day, s.currency, p.eur_per_unit,
       CASE WHEN p.day = s.day THEN 'published' ELSE 'carried' END AS fx_source
FROM spine s
ASOF LEFT JOIN published p ON s.currency = p.currency AND s.day >= p.day
UNION ALL
SELECT DISTINCT day, 'EUR', 1.0, 'published' FROM spine;
