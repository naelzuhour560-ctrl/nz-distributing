-- Source of truth: live Supabase DB, exported 2026-08-20.
-- Re-run this file on a fresh database to recreate all functions.
--
-- Function bodies are verbatim pg_get_functiondef() output from the running
-- database, not reconstructions. Table DDL is rebuilt from pg_attribute,
-- pg_constraint and pg_indexes on the same connection.
--
-- PREREQUISITE — this file is not self-sufficient. Every function here is
-- LANGUAGE sql, and Postgres validates SQL function bodies at CREATE time, so
-- these will fail on a genuinely empty database. The Phase 1 base tables must
-- exist first:
--
--     routes, products, stores, invoice_lines, order_lines
--
-- Those tables have no committed DDL anywhere in this repo; they are described
-- in prose in docs/phase-1.md section 2 and were created by hand in the
-- Supabase console. Until they are exported too, "fresh database" means one
-- that already has the Phase 1 schema.
--
-- Contents:
--   1. Tables      forecasts, reminders  (Phase 3 and Phase 4)
--   2. Functions   13 RPCs called by the dashboard and the Python scripts


-- ============================================================================
-- 1. TABLES
-- ============================================================================

-- Phase 3 output: one row per (store, product) for a forecast week.
-- The UNIQUE constraint is the upsert key used by
-- scripts/forecast_model.py --write; it includes week_start, so a re-run for a
-- new week adds rows rather than replacing the previous week's.
CREATE TABLE IF NOT EXISTS public.forecasts (
    id               bigserial    PRIMARY KEY,
    location_id      integer      NOT NULL REFERENCES public.routes (location_id),
    store_name       text         NOT NULL,
    upc              text         NOT NULL REFERENCES public.products (upc),
    week_start       date         NOT NULL,
    predicted_units  numeric(10,2) NOT NULL,
    model_version    text         NOT NULL,
    generated_at     timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (location_id, store_name, upc, week_start, model_version)
);

CREATE INDEX IF NOT EXISTS idx_forecasts_week
    ON public.forecasts USING btree (week_start);
CREATE INDEX IF NOT EXISTS idx_forecasts_store
    ON public.forecasts USING btree (location_id, store_name);


-- Phase 4 output: one drafted reorder message per store per week.
-- The UNIQUE constraint is the upsert key used by
-- scripts/generate_reminders.py.
--
-- NOTE: status has no CHECK constraint in the live database — it accepts any
-- text. The application writes only 'draft', 'approved' and 'sent'
-- (docs/phase-4-reminders.md section 4). Nothing at the schema level enforces
-- that, so a typo in a client would be stored silently.
CREATE TABLE IF NOT EXISTS public.reminders (
    id                     bigserial     PRIMARY KEY,
    location_id            integer       NOT NULL REFERENCES public.routes (location_id),
    store_name             text          NOT NULL,
    week_start             date          NOT NULL,
    draft_message          text          NOT NULL,
    top_products           jsonb         NOT NULL,
    predicted_total_units  numeric(10,2) NOT NULL,
    status                 text          NOT NULL DEFAULT 'draft',
    generated_at           timestamptz   NOT NULL DEFAULT now(),
    approved_at            timestamptz,
    UNIQUE (location_id, store_name, week_start)
);


-- ============================================================================
-- 2. FUNCTIONS
-- ============================================================================


-- --------------------------------------------------------------------------
-- churn_overview()
-- called by: app/churn/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.churn_overview()
 RETURNS TABLE(location_id integer, store_name text, last_sale_date date, avg_days_between_orders numeric, days_since_last_sale integer, sale_revenue numeric, churn_ratio numeric)
 LANGUAGE sql
 STABLE
AS $function$
  WITH dataset_end AS (
    SELECT max(calendar_date) AS last_date FROM invoice_lines
  ),
  per_store AS (
    SELECT
      il.location_id,
      il.store_name,
      max(il.calendar_date) FILTER (WHERE il.transaction_type = 'Sale') AS last_sale,
      count(DISTINCT il.calendar_date) FILTER (WHERE il.transaction_type = 'Sale') AS order_days,
      min(il.calendar_date) FILTER (WHERE il.transaction_type = 'Sale') AS first_sale,
      sum(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale') AS revenue
    FROM invoice_lines il
    GROUP BY il.location_id, il.store_name
  )
  SELECT
    ps.location_id,
    ps.store_name,
    ps.last_sale::date,
    CASE WHEN ps.order_days > 1
      THEN round((ps.last_sale - ps.first_sale)::numeric / (ps.order_days - 1), 1)
      ELSE NULL END AS avg_days_between_orders,
    (de.last_date - ps.last_sale)::integer AS days_since_last_sale,
    COALESCE(ps.revenue, 0) AS sale_revenue,
    CASE WHEN ps.order_days > 1 AND (ps.last_sale - ps.first_sale) > 0
      THEN round((de.last_date - ps.last_sale)::numeric / ((ps.last_sale - ps.first_sale)::numeric / (ps.order_days - 1)), 1)
      ELSE NULL END AS churn_ratio
  FROM per_store ps
  CROSS JOIN dataset_end de
  WHERE ps.last_sale IS NOT NULL
  ORDER BY churn_ratio DESC NULLS LAST;
$function$;


-- --------------------------------------------------------------------------
-- dead_stock()
-- called by: app/declining/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.dead_stock()
 RETURNS TABLE(upc text, product_name text, total_units bigint, total_dollars numeric, last_90_units bigint, prior_units bigint, last_sale_date date, pct_decline numeric)
 LANGUAGE sql
 STABLE
AS $function$
  WITH bounds AS (
    SELECT max(calendar_date) AS end_date FROM invoice_lines
  ),
  per_product AS (
    SELECT
      il.upc,
      p.product_name,
      SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale') AS total_units,
      SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale') AS total_dollars,
      SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale' AND il.calendar_date > b.end_date - INTERVAL '90 days') AS last_90_units,
      SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale' AND il.calendar_date <= b.end_date - INTERVAL '90 days' AND il.calendar_date > b.end_date - INTERVAL '180 days') AS prior_units,
      MAX(il.calendar_date) FILTER (WHERE il.transaction_type = 'Sale') AS last_sale
    FROM invoice_lines il
    JOIN products p ON p.upc = il.upc
    CROSS JOIN bounds b
    GROUP BY il.upc, p.product_name
  )
  SELECT
    upc,
    product_name,
    COALESCE(total_units, 0)::bigint,
    COALESCE(total_dollars, 0),
    COALESCE(last_90_units, 0)::bigint,
    COALESCE(prior_units, 0)::bigint,
    last_sale::date,
    CASE WHEN COALESCE(prior_units, 0) > 0
      THEN round(100.0 * (COALESCE(prior_units,0) - COALESCE(last_90_units,0)) / prior_units, 1)
      ELSE NULL END AS pct_decline
  FROM per_product
  WHERE COALESCE(total_units, 0) > 0
  ORDER BY pct_decline DESC NULLS LAST;
$function$;


-- --------------------------------------------------------------------------
-- forecast_next_week()
-- called by: app/forecasts/page.tsx, scripts/generate_reminders.py
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.forecast_next_week()
 RETURNS TABLE(location_id integer, store_name text, upc text, product_name text, week_start date, predicted_units numeric)
 LANGUAGE sql
AS $function$
    SELECT f.location_id, f.store_name, f.upc, p.product_name,
           f.week_start, f.predicted_units
    FROM forecasts f
    JOIN products p ON p.upc = f.upc
    WHERE f.week_start = (SELECT MAX(week_start) FROM forecasts)
    ORDER BY f.location_id, f.store_name, f.predicted_units DESC;
$function$;


-- --------------------------------------------------------------------------
-- invoice_lines_totals()
-- called by: app/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.invoice_lines_totals()
 RETURNS TABLE(row_count bigint, total_units bigint, total_wholesale_dollars numeric)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    COUNT(*)::bigint,
    COALESCE(SUM(units), 0)::bigint,
    COALESCE(SUM(total_wholesale_dollars), 0)
  FROM invoice_lines;
$function$;


-- --------------------------------------------------------------------------
-- monthly_revenue()
-- called by: app/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.monthly_revenue()
 RETURNS TABLE(month date, sale_dollars numeric, return_dollars numeric, buyback_dollars numeric, net_dollars numeric, sale_units bigint)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    date_trunc('month', il.calendar_date)::date AS month,
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale'), 0),
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Return'), 0),
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Buyback'), 0),
    COALESCE(SUM(il.total_wholesale_dollars), 0),
    COALESCE(SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale'), 0)::bigint
  FROM invoice_lines il
  GROUP BY date_trunc('month', il.calendar_date)
  ORDER BY month;
$function$;


-- --------------------------------------------------------------------------
-- promo_spend()
-- called by: app/promotions/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.promo_spend()
 RETURNS TABLE(upc text, product_name text, sale_units bigint, sale_dollars numeric, promo_dollars numeric, promo_pct_of_sales numeric, promo_per_unit numeric)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    il.upc,
    p.product_name,
    SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale')::bigint AS sale_units,
    SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale') AS sale_dollars,
    SUM(il.total_promotion_allowance) FILTER (WHERE il.transaction_type = 'Sale') AS promo_dollars,
    CASE WHEN SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale') > 0
      THEN round(100.0 * SUM(il.total_promotion_allowance) FILTER (WHERE il.transaction_type = 'Sale')
           / SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale'), 1)
      ELSE NULL END AS promo_pct_of_sales,
    CASE WHEN SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale') > 0
      THEN round(SUM(il.total_promotion_allowance) FILTER (WHERE il.transaction_type = 'Sale')
           / SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale'), 3)
      ELSE NULL END AS promo_per_unit
  FROM invoice_lines il
  JOIN products p ON p.upc = il.upc
  GROUP BY il.upc, p.product_name
  HAVING SUM(il.total_promotion_allowance) FILTER (WHERE il.transaction_type = 'Sale') > 0
  ORDER BY SUM(il.total_promotion_allowance) FILTER (WHERE il.transaction_type = 'Sale') DESC;
$function$;


-- --------------------------------------------------------------------------
-- revenue_by_route()
-- called by: app/routes/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.revenue_by_route()
 RETURNS TABLE(location_id integer, route_name text, transaction_type text, line_count bigint, total_units bigint, total_wholesale_dollars numeric)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    il.location_id,
    r.route_name,
    il.transaction_type,
    COUNT(*)::bigint,
    COALESCE(SUM(il.units), 0)::bigint,
    COALESCE(SUM(il.total_wholesale_dollars), 0)
  FROM invoice_lines il
  JOIN routes r ON r.location_id = il.location_id
  GROUP BY il.location_id, r.route_name, il.transaction_type
  ORDER BY il.location_id, il.transaction_type;
$function$;


-- --------------------------------------------------------------------------
-- store_basket(integer,text)
-- called by: app/stores/[route]/[store]/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.store_basket(p_location_id integer, p_store_name text)
 RETURNS TABLE(upc text, product_name text, sale_dollars numeric, net_dollars numeric, sale_units bigint)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    il.upc,
    p.product_name,
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale'), 0),
    COALESCE(SUM(il.total_wholesale_dollars), 0),
    COALESCE(SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale'), 0)::bigint
  FROM invoice_lines il
  JOIN products p ON p.upc = il.upc
  WHERE il.location_id = p_location_id
    AND il.store_name = p_store_name
  GROUP BY il.upc, p.product_name
  ORDER BY COALESCE(SUM(il.total_wholesale_dollars), 0) DESC;
$function$;


-- --------------------------------------------------------------------------
-- store_churn(integer,text)
-- called by: app/stores/[route]/[store]/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.store_churn(p_location_id integer, p_store_name text)
 RETURNS TABLE(last_sale_date date, avg_days_between_orders numeric, days_since_last_sale integer)
 LANGUAGE sql
 STABLE
AS $function$
  WITH sale_dates AS (
    SELECT DISTINCT calendar_date
    FROM invoice_lines
    WHERE location_id = p_location_id
      AND store_name  = p_store_name
      AND transaction_type = 'Sale'
  ),
  gaps AS (
    SELECT calendar_date,
           calendar_date - lag(calendar_date) OVER (ORDER BY calendar_date) AS gap
    FROM sale_dates
  ),
  dataset_end AS (
    SELECT max(calendar_date) AS last_date FROM invoice_lines
  )
  SELECT
    max(sd.calendar_date)::date AS last_sale_date,
    round(avg(g.gap), 1) AS avg_days_between_orders,
    (de.last_date - max(sd.calendar_date))::int AS days_since_last_sale
  FROM sale_dates sd
  CROSS JOIN dataset_end de
  LEFT JOIN gaps g ON g.calendar_date = sd.calendar_date AND g.gap IS NOT NULL
  GROUP BY de.last_date;
$function$;


-- --------------------------------------------------------------------------
-- store_margin(integer,text)
-- called by: app/stores/[route]/[store]/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.store_margin(p_location_id integer, p_store_name text)
 RETURNS TABLE(sale_revenue numeric, sale_cost numeric, gross_margin numeric, margin_pct numeric)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    COALESCE(SUM(il.total_wholesale_dollars), 0) AS sale_revenue,
    COALESCE(SUM(il.distributor_unit_cost * il.units), 0) AS sale_cost,
    COALESCE(SUM(il.total_wholesale_dollars) - SUM(il.distributor_unit_cost * il.units), 0) AS gross_margin,
    CASE WHEN COALESCE(SUM(il.total_wholesale_dollars), 0) <> 0
      THEN ROUND(100 * (SUM(il.total_wholesale_dollars) - SUM(il.distributor_unit_cost * il.units)) / SUM(il.total_wholesale_dollars), 1)
      ELSE NULL END AS margin_pct
  FROM invoice_lines il
  WHERE il.location_id = p_location_id
    AND il.store_name = p_store_name
    AND il.transaction_type = 'Sale';
$function$;


-- --------------------------------------------------------------------------
-- store_monthly(integer,text)
-- called by: app/stores/[route]/[store]/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.store_monthly(p_location_id integer, p_store_name text)
 RETURNS TABLE(month date, sale_dollars numeric, return_dollars numeric, buyback_dollars numeric, net_dollars numeric, sale_units bigint)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    date_trunc('month', il.calendar_date)::date AS month,
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale'), 0),
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Return'), 0),
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Buyback'), 0),
    COALESCE(SUM(il.total_wholesale_dollars), 0),
    COALESCE(SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale'), 0)::bigint
  FROM invoice_lines il
  WHERE il.location_id = p_location_id
    AND il.store_name = p_store_name
  GROUP BY date_trunc('month', il.calendar_date)
  ORDER BY month;
$function$;


-- --------------------------------------------------------------------------
-- top_products()
-- called by: app/products/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.top_products()
 RETURNS TABLE(upc text, product_name text, sale_dollars numeric, return_dollars numeric, buyback_dollars numeric, net_dollars numeric, sale_units bigint)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    il.upc,
    p.product_name,
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale'), 0),
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Return'), 0),
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Buyback'), 0),
    COALESCE(SUM(il.total_wholesale_dollars), 0),
    COALESCE(SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale'), 0)::bigint
  FROM invoice_lines il
  JOIN products p ON p.upc = il.upc
  GROUP BY il.upc, p.product_name
  ORDER BY COALESCE(SUM(il.total_wholesale_dollars), 0) DESC;
$function$;


-- --------------------------------------------------------------------------
-- top_stores()
-- called by: app/stores/page.tsx
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.top_stores()
 RETURNS TABLE(store_name text, location_id integer, sale_dollars numeric, return_dollars numeric, buyback_dollars numeric, net_dollars numeric, sale_units bigint)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    il.store_name,
    il.location_id,
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Sale'), 0),
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Return'), 0),
    COALESCE(SUM(il.total_wholesale_dollars) FILTER (WHERE il.transaction_type = 'Buyback'), 0),
    COALESCE(SUM(il.total_wholesale_dollars), 0),
    COALESCE(SUM(il.units) FILTER (WHERE il.transaction_type = 'Sale'), 0)::bigint
  FROM invoice_lines il
  GROUP BY il.store_name, il.location_id
  ORDER BY COALESCE(SUM(il.total_wholesale_dollars), 0) DESC;
$function$;
