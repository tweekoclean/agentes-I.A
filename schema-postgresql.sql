-- Nelvo Company 0.6.0: criar em um banco vazio, uma única vez.

CREATE TABLE application_rates (
	key VARCHAR(100) NOT NULL,
	attempts INTEGER NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (key)
)

;


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


CREATE TABLE support_tenants (
	id VARCHAR(36) NOT NULL,
	name VARCHAR(200) NOT NULL,
	site_key_hash VARCHAR(64) NOT NULL,
	allowed_origins JSON NOT NULL,
	welcome_text TEXT NOT NULL,
	active BOOLEAN NOT NULL,
	ai_enabled BOOLEAN NOT NULL,
	daily_conversation_limit INTEGER NOT NULL,
	daily_ai_limit INTEGER NOT NULL,
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


CREATE TABLE sales_applications (
	id VARCHAR(36) NOT NULL,
	submission_id VARCHAR(36),
	lead_id VARCHAR(36),
	tenant_id VARCHAR(36),
	name VARCHAR(200) NOT NULL,
	city VARCHAR(100) NOT NULL,
	segment VARCHAR(50) NOT NULL,
	contact_name VARCHAR(150) NOT NULL,
	phone VARCHAR(20),
	channels JSON NOT NULL,
	volume VARCHAR(30) NOT NULL,
	goals TEXT NOT NULL,
	contact_permission BOOLEAN NOT NULL,
	source VARCHAR(30) NOT NULL,
	stage VARCHAR(30) NOT NULL,
	notes TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (submission_id),
	UNIQUE (lead_id),
	FOREIGN KEY(lead_id) REFERENCES leads (id),
	UNIQUE (tenant_id),
	FOREIGN KEY(tenant_id) REFERENCES support_tenants (id)
)

;


CREATE TABLE support_conversations (
	id VARCHAR(36) NOT NULL,
	tenant_id VARCHAR(36) NOT NULL,
	channel VARCHAR(20) NOT NULL,
	recipient VARCHAR(20),
	token_hash VARCHAR(64),
	origin VARCHAR(300),
	state VARCHAR(30) NOT NULL,
	pause_reason VARCHAR(100),
	last_inbound_at TIMESTAMP WITH TIME ZONE,
	last_inbound_id VARCHAR(36),
	opted_out_at TIMESTAMP WITH TIME ZONE,
	resumed_at TIMESTAMP WITH TIME ZONE,
	auto_replies INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_support_recipient UNIQUE (tenant_id, channel, recipient),
	FOREIGN KEY(tenant_id) REFERENCES support_tenants (id)
)

;


CREATE TABLE support_knowledge (
	id VARCHAR(36) NOT NULL,
	tenant_id VARCHAR(36) NOT NULL,
	title VARCHAR(200) NOT NULL,
	content TEXT NOT NULL,
	active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id) REFERENCES support_tenants (id)
)

;


CREATE TABLE support_quotas (
	tenant_id VARCHAR(36) NOT NULL,
	day DATE NOT NULL,
	conversations_opened INTEGER NOT NULL,
	ai_calls INTEGER NOT NULL,
	PRIMARY KEY (tenant_id, day),
	FOREIGN KEY(tenant_id) REFERENCES support_tenants (id)
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


CREATE TABLE support_handoffs (
	id VARCHAR(36) NOT NULL,
	tenant_id VARCHAR(36) NOT NULL,
	conversation_id VARCHAR(36) NOT NULL,
	reason VARCHAR(100) NOT NULL,
	summary TEXT NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	closed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id) REFERENCES support_tenants (id),
	FOREIGN KEY(conversation_id) REFERENCES support_conversations (id)
)

;


CREATE TABLE support_messages (
	id VARCHAR(36) NOT NULL,
	tenant_id VARCHAR(36) NOT NULL,
	conversation_id VARCHAR(36) NOT NULL,
	direction VARCHAR(10) NOT NULL,
	author VARCHAR(20) NOT NULL,
	kind VARCHAR(20) NOT NULL,
	text TEXT NOT NULL,
	client_message_id VARCHAR(64),
	reply_to_id VARCHAR(36),
	provider_message_id VARCHAR(250),
	sender_id VARCHAR(25),
	status VARCHAR(40) NOT NULL,
	delivery_status VARCHAR(20),
	engine VARCHAR(60),
	attempts INTEGER NOT NULL,
	error TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	processing_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_support_client_message UNIQUE (conversation_id, client_message_id),
	FOREIGN KEY(tenant_id) REFERENCES support_tenants (id),
	FOREIGN KEY(conversation_id) REFERENCES support_conversations (id),
	UNIQUE (reply_to_id),
	FOREIGN KEY(reply_to_id) REFERENCES support_messages (id),
	UNIQUE (provider_message_id)
)

;

CREATE INDEX ix_application_rates_expires_at ON application_rates (expires_at);

CREATE INDEX ix_leads_city ON leads (city);

CREATE INDEX ix_leads_review_status ON leads (review_status);

CREATE INDEX ix_leads_segment ON leads (segment);

CREATE INDEX ix_leads_consent_status ON leads (consent_status);

CREATE INDEX ix_leads_is_demo ON leads (is_demo);

CREATE INDEX ix_whatsapp_status_events_provider_message_id ON whatsapp_status_events (provider_message_id);

CREATE INDEX ix_commercial_conversations_lead_id ON commercial_conversations (lead_id);

CREATE INDEX ix_consent_events_lead_id ON consent_events (lead_id);

CREATE INDEX ix_sales_applications_stage ON sales_applications (stage);

CREATE INDEX ix_support_conversations_state ON support_conversations (state);

CREATE INDEX ix_support_conversations_tenant_id ON support_conversations (tenant_id);

CREATE INDEX ix_support_knowledge_tenant_id ON support_knowledge (tenant_id);

CREATE INDEX ix_commercial_handoffs_conversation_id ON commercial_handoffs (conversation_id);

CREATE INDEX ix_commercial_handoffs_status ON commercial_handoffs (status);

CREATE INDEX ix_commercial_messages_status ON commercial_messages (status);

CREATE INDEX ix_commercial_messages_lead_id ON commercial_messages (lead_id);

CREATE INDEX ix_commercial_messages_conversation_id ON commercial_messages (conversation_id);

CREATE INDEX ix_support_handoffs_status ON support_handoffs (status);

CREATE INDEX ix_support_handoffs_conversation_id ON support_handoffs (conversation_id);

CREATE INDEX ix_support_handoffs_tenant_id ON support_handoffs (tenant_id);

CREATE INDEX ix_support_messages_conversation_id ON support_messages (conversation_id);

CREATE INDEX ix_support_messages_status ON support_messages (status);

CREATE INDEX ix_support_messages_tenant_id ON support_messages (tenant_id);
