-- SchemaDiff drift fixture (MySQL), source side. Compare with drift_target.sql.
-- Apply with: mysql -h127.0.0.1 -P<port> -uroot -p < drift_source.sql
DROP DATABASE IF EXISTS drift_source;
CREATE DATABASE drift_source;
USE drift_source;

CREATE TABLE users (
    id          int NOT NULL AUTO_INCREMENT,
    email       varchar(255) NOT NULL,
    name        varchar(100),
    status      enum('active','inactive','pending') NOT NULL DEFAULT 'active',
    bio         text,
    handle      varchar(50) COLLATE utf8mb4_bin,
    score       int NOT NULL DEFAULT 0,
    full_label  varchar(120) GENERATED ALWAYS AS (concat(name, '!')) STORED,
    PRIMARY KEY (id),
    UNIQUE KEY users_email_key (email),
    KEY idx_users_status (status)
) COMMENT = 'registered users';
ALTER TABLE users MODIFY email varchar(255) NOT NULL COMMENT 'login email';

CREATE TABLE orders (
    id        bigint NOT NULL AUTO_INCREMENT,
    user_id   int NOT NULL,
    total     decimal(10,2) NOT NULL DEFAULT 0,
    note      varchar(100),
    placed_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_orders_user_placed (user_id, placed_at),
    KEY idx_orders_lower_note ((lower(note))),
    CONSTRAINT orders_user_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT orders_total_check CHECK (total >= 0)
);

CREATE TABLE products (
    sku   varchar(40) NOT NULL,
    name  varchar(100) NOT NULL,
    descr text,
    price decimal(8,2) NOT NULL,
    qty   int NOT NULL,
    PRIMARY KEY (sku),
    KEY idx_products_name (name),
    FULLTEXT KEY idx_products_descr (descr),
    CONSTRAINT products_qty_check CHECK (qty >= 0)
);

CREATE TABLE tags (
    id  int NOT NULL,
    tag varchar(50) NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE audit_log (
    id      int NOT NULL,
    message text,
    PRIMARY KEY (id)
);

-- Written differently on each side, but logically identical: must report nothing.
CREATE TABLE equivalent_forms (
    id         integer NOT NULL,
    label      varchar(50) NOT NULL DEFAULT 'n/a',
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ratio      numeric(6,2) DEFAULT 1.50,
    flag       bool NOT NULL DEFAULT true,
    PRIMARY KEY (id),
    CONSTRAINT equivalent_forms_ratio_check CHECK (ratio > 0)
);

CREATE VIEW active_users AS SELECT id, email FROM users WHERE status = 'active';
CREATE VIEW order_totals AS SELECT user_id, sum(total) AS total FROM orders GROUP BY user_id;
