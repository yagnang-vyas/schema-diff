-- SchemaDiff drift fixture (PostgreSQL), target side. Compare with drift_source.sql.
-- Apply with: psql "$SCHEMADIFF_PG_URL" -f drift_target.sql
DROP SCHEMA IF EXISTS drift_target CASCADE;
CREATE SCHEMA drift_target;
SET search_path = drift_target;

CREATE TYPE status_enum AS ENUM ('active', 'inactive', 'pending', 'archived');

CREATE TABLE users (
    id          serial PRIMARY KEY,
    email       varchar(255) NOT NULL,
    name        text NOT NULL,
    status      status_enum NOT NULL DEFAULT 'active',
    nickname    text,
    handle      text,
    full_label  text GENERATED ALWAYS AS (name || '?') STORED
);
COMMENT ON COLUMN users.email IS 'account email';

CREATE TABLE orders (
    id        bigint PRIMARY KEY,
    user_id   integer NOT NULL,
    total     numeric(10,2) NOT NULL DEFAULT 1,
    note      varchar(200),
    placed_at timestamp NOT NULL DEFAULT now(),
    CONSTRAINT orders_user_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT orders_total_check CHECK (total > 0)
);
CREATE INDEX idx_orders_user_placed ON orders (placed_at, user_id);
CREATE INDEX idx_orders_open ON orders (placed_at) WHERE total > 100;

CREATE TABLE products (
    sku   text PRIMARY KEY,
    name  text NOT NULL,
    price numeric(8,2) NOT NULL,
    qty   integer NOT NULL
);
CREATE INDEX idx_products_name ON products USING hash (name);
CREATE INDEX idx_products_sku_price ON products (sku, price);

CREATE TABLE tags (
    id  integer NOT NULL,
    tag text NOT NULL,
    PRIMARY KEY (id, tag)
);

CREATE TABLE extra_table (
    id integer PRIMARY KEY
);

CREATE TABLE equivalent_forms (
    id         integer PRIMARY KEY,
    label      varchar(50) NOT NULL DEFAULT 'n/a',
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ratio      float8 DEFAULT 1.5,
    flag       bool NOT NULL DEFAULT TRUE,
    CONSTRAINT equivalent_forms_ratio_check CHECK (ratio > 0)
);

CREATE VIEW active_users AS SELECT id, email FROM users WHERE status = 'pending';
CREATE VIEW order_totals AS
    SELECT user_id,
           sum(total) AS total
    FROM   orders
    GROUP  BY user_id;
