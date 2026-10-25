-- SchemaDiff drift fixture (MySQL), target side. Compare with drift_source.sql.
-- Apply with: mysql -h127.0.0.1 -P<port> -uroot -p < drift_target.sql
DROP DATABASE IF EXISTS drift_target;
CREATE DATABASE drift_target;
USE drift_target;

CREATE TABLE users (
    id          int NOT NULL AUTO_INCREMENT,
    email       varchar(255) NOT NULL COMMENT 'account email',
    name        varchar(100) NOT NULL,
    status      enum('active','inactive','pending','archived') NOT NULL DEFAULT 'active',
    nickname    varchar(50),
    handle      varchar(50),
    score       int NOT NULL DEFAULT 10,
    full_label  varchar(120) GENERATED ALWAYS AS (concat(name, '?')) STORED,
    PRIMARY KEY (id)
) COMMENT = 'application users';

CREATE TABLE orders (
    id        bigint NOT NULL,
    user_id   int NOT NULL,
    total     decimal(10,2) NOT NULL DEFAULT 0,
    note      varchar(200),
    placed_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_orders_user_placed (placed_at, user_id),
    KEY idx_orders_lower_note ((upper(note))),
    CONSTRAINT orders_user_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT orders_total_check CHECK (total > 0)
);

CREATE TABLE products (
    sku   varchar(40) NOT NULL,
    name  varchar(100) NOT NULL,
    descr text,
    price decimal(8,2) NOT NULL,
    qty   int NOT NULL,
    PRIMARY KEY (sku),
    KEY idx_products_name (name),
    KEY idx_products_descr (descr(100))
);

CREATE TABLE tags (
    id  int NOT NULL,
    tag varchar(50) NOT NULL,
    PRIMARY KEY (id, tag)
);

CREATE TABLE extra_table (
    id int NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE equivalent_forms (
    id         int NOT NULL,
    label      varchar(50) NOT NULL DEFAULT 'n/a',
    created_at timestamp NOT NULL DEFAULT now(),
    ratio      decimal(6,2) DEFAULT 1.5,
    flag       tinyint(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    CONSTRAINT equivalent_forms_ratio_check CHECK ((`ratio`>0))
);

CREATE VIEW active_users AS SELECT id, email FROM users WHERE status = 'pending';
CREATE VIEW order_totals AS
    SELECT user_id,
           sum(total) AS total
    FROM   orders
    GROUP  BY user_id;
