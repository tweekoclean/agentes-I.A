-- AtendeAI 0.2.0: criar em um banco vazio, uma única vez.

CREATE TABLE commercial_quotas (
	day DATE NOT NULL,
	opening_attempts INTEGER NOT NULL,
	PRIMARY KEY (day)
)

;


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


CREATE TABLE whatsapp_status_events (
	id VARCHAR(36) NOT NULL,
	provider_message_id VARCHAR(250) NOT NULL,
	recipient VARCHAR(20) NOT NULL,
	status VARCHAR(20) NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	error_code VARCHAR(40),
	PRIMARY KEY (id),
	CONSTRAINT uq_whatsapp_status UNIQUE (provider_message_id, status, occurred_at)
)

;


CREATE TABLE commercial_conversations (
	id VARCHAR(36) NOT NULL,
	recipient VARCHAR(20) NOT NULL,
	lead_id VARCHAR(36),
	last_inbound_at TIMESTAMP WITH TIME ZONE,
	last_inbound_id VARCHAR(36),
	opted_out_at TIMESTAMP WITH TIME ZONE,
	paused BOOLEAN NOT NULL,
	pause_reason VARCHAR(100),
	auto_replies INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (recipient),
	FOREIGN KEY(lead_id) REFERENCES leads (id)
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


CREATE TABLE commercial_handoffs (
	id VARCHAR(36) NOT NULL,
	conversation_id VARCHAR(36) NOT NULL,
	reason VARCHAR(100) NOT NULL,
	summary TEXT NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	closed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(conversation_id) REFERENCES commercial_conversations (id)
)

;


CREATE TABLE commercial_messages (
	id VARCHAR(36) NOT NULL,
	lead_id VARCHAR(36),
	conversation_id VARCHAR(36),
	recipient VARCHAR(20),
	sender_id VARCHAR(25),
	direction VARCHAR(10) NOT NULL,
	kind VARCHAR(20) NOT NULL,
	purpose VARCHAR(30) NOT NULL,
	text TEXT NOT NULL,
	payload JSON,
	status VARCHAR(40) NOT NULL,
	delivery_status VARCHAR(20),
	provider_message_id VARCHAR(250),
	reply_to_id VARCHAR(36),
	opening_key VARCHAR(64),
	engine VARCHAR(60),
	attempts INTEGER NOT NULL,
	error TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	approved_at TIMESTAMP WITH TIME ZONE,
	available_at TIMESTAMP WITH TIME ZONE NOT NULL,
	processing_at TIMESTAMP WITH TIME ZONE,
	sent_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(lead_id) REFERENCES leads (id),
	FOREIGN KEY(conversation_id) REFERENCES commercial_conversations (id),
	UNIQUE (provider_message_id),
	UNIQUE (reply_to_id),
	FOREIGN KEY(reply_to_id) REFERENCES commercial_messages (id),
	UNIQUE (opening_key)
)

;

CREATE INDEX ix_leads_city ON leads (city);

CREATE INDEX ix_leads_consent_status ON leads (consent_status);

CREATE INDEX ix_leads_segment ON leads (segment);

CREATE INDEX ix_leads_is_demo ON leads (is_demo);

CREATE INDEX ix_leads_review_status ON leads (review_status);

CREATE INDEX ix_whatsapp_status_events_provider_message_id ON whatsapp_status_events (provider_message_id);

CREATE INDEX ix_commercial_conversations_lead_id ON commercial_conversations (lead_id);

CREATE INDEX ix_consent_events_lead_id ON consent_events (lead_id);

CREATE INDEX ix_commercial_handoffs_conversation_id ON commercial_handoffs (conversation_id);

CREATE INDEX ix_commercial_handoffs_status ON commercial_handoffs (status);

CREATE INDEX ix_commercial_messages_status ON commercial_messages (status);

CREATE INDEX ix_commercial_messages_lead_id ON commercial_messages (lead_id);

CREATE INDEX ix_commercial_messages_conversation_id ON commercial_messages (conversation_id);
