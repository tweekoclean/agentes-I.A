-- AtendeAI 0.1.0: criar em um banco vazio, uma única vez.

CREATE TABLE leads (
	id VARCHAR(36) NOT NULL,
	name VARCHAR(300) NOT NULL,
	city VARCHAR(100) NOT NULL,
	city_ibge VARCHAR(7) NOT NULL,
	segment VARCHAR(50) NOT NULL,
	address TEXT,
	phone_public VARCHAR(250),
	phone_normalized VARCHAR(20),
	website TEXT,
	email_public VARCHAR(300),
	opening_hours TEXT,
	source VARCHAR(50) NOT NULL,
	source_ref VARCHAR(100) NOT NULL,
	source_url TEXT NOT NULL,
	source_license TEXT NOT NULL,
	is_demo BOOLEAN NOT NULL,
	priority INTEGER NOT NULL,
	review_status VARCHAR(30) NOT NULL,
	review_note TEXT,
	consent_status VARCHAR(30) NOT NULL,
	whatsapp_recipient VARCHAR(20),
	analysis JSON,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_lead_source UNIQUE (source, source_ref)
)

;


CREATE TABLE provider_leases (
	name VARCHAR(50) NOT NULL,
	next_allowed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (name)
)

;


CREATE TABLE search_cache (
	key VARCHAR(64) NOT NULL,
	payload JSON NOT NULL,
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (key)
)

;


CREATE TABLE search_runs (
	id VARCHAR(36) NOT NULL,
	city VARCHAR(100) NOT NULL,
	segments JSON NOT NULL,
	source VARCHAR(50) NOT NULL,
	cached BOOLEAN NOT NULL,
	found INTEGER NOT NULL,
	inserted INTEGER NOT NULL,
	updated INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
)

;


CREATE TABLE consent_events (
	id VARCHAR(36) NOT NULL,
	lead_id VARCHAR(36) NOT NULL,
	status VARCHAR(30) NOT NULL,
	recipient VARCHAR(20) NOT NULL,
	evidence TEXT NOT NULL,
	purpose VARCHAR(100) NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	registered_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(lead_id) REFERENCES leads (id)
)

;

CREATE INDEX ix_leads_review_status ON leads (review_status);

CREATE INDEX ix_leads_city ON leads (city);

CREATE INDEX ix_leads_consent_status ON leads (consent_status);

CREATE INDEX ix_leads_is_demo ON leads (is_demo);

CREATE INDEX ix_leads_segment ON leads (segment);

CREATE INDEX ix_consent_events_lead_id ON consent_events (lead_id);
