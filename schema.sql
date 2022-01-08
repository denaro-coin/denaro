CREATE TABLE IF NOT EXISTS blocks (
	id SERIAL PRIMARY KEY,
	hash CHAR(64) UNIQUE,
	address VARCHAR(128) NOT NULL,
	random BIGINT NOT NULL,
	difficulty NUMERIC(3, 1) NOT NULL,
	reward NUMERIC(14, 6) NOT NULL,
	timestamp TIMESTAMP(0)
);

CREATE TABLE IF NOT EXISTS transactions (
	block_hash CHAR(64) NOT NULL REFERENCES blocks(hash) ON DELETE CASCADE,
	tx_hash CHAR(64) UNIQUE,
	tx_hex VARCHAR(2048) UNIQUE,
	inputs_addresses TEXT[],
	fees NUMERIC(14, 6) NOT NULL
);

CREATE TYPE tx_output AS (
    tx_hash CHAR(64),
    index SMALLINT
);

CREATE TABLE IF NOT EXISTS unspent_outputs (
	tx_hash CHAR(64) REFERENCES transactions(tx_hash) ON DELETE CASCADE,
	index SMALLINT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_transactions (
	tx_hash CHAR(64) UNIQUE,
	tx_hex VARCHAR(2048) UNIQUE,
	inputs_addresses TEXT[],
	fees NUMERIC(14, 6) NOT NULL
);

-- if your user is denaro
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO denaro;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO denaro;