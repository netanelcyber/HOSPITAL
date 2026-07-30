import { Pool } from 'pg';
import { config } from '../config';
import { Logger } from '../utils/logger';

const logger = new Logger();

export let pool: Pool;

export async function setupDatabase() {
  pool = new Pool({
    host: config.database.host,
    port: config.database.port,
    user: config.database.username,
    password: config.database.password,
    database: config.database.database,
    max: 20,
  });

  pool.on('error', (err) => {
    logger.error('Unexpected error on idle client', err);
  });

  // Test connection
  const client = await pool.connect();
  await client.query('SELECT NOW()');
  client.release();

  logger.info('Database connected successfully');

  // Create tables
  await initializeTables();
}

export async function query(text: string, params?: any[]) {
  const start = Date.now();
  try {
    const result = await pool.query(text, params);
    const duration = Date.now() - start;
    logger.debug(`Query executed in ${duration}ms`, { query: text.substring(0, 100) });
    return result;
  } catch (error) {
    logger.error('Database query error', error);
    throw error;
  }
}

async function initializeTables() {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // Users table
    await client.query(`
      CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username VARCHAR(255) UNIQUE NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        full_name VARCHAR(255),
        role VARCHAR(50) DEFAULT 'user',
        status VARCHAR(50) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Documents table
    await client.query(`
      CREATE TABLE IF NOT EXISTS documents (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(255) NOT NULL,
        owner_id UUID NOT NULL REFERENCES users(id),
        type VARCHAR(50),
        storage_path VARCHAR(512) NOT NULL,
        size_bytes BIGINT,
        mime_type VARCHAR(100),
        checksum VARCHAR(64),
        is_deleted BOOLEAN DEFAULT false,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(owner_id, storage_path)
      )
    `);

    // Document versions table
    await client.query(`
      CREATE TABLE IF NOT EXISTS document_versions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        version_number INT NOT NULL,
        storage_path VARCHAR(512) NOT NULL,
        created_by UUID NOT NULL REFERENCES users(id),
        change_description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(document_id, version_number)
      )
    `);

    // Sharing table
    await client.query(`
      CREATE TABLE IF NOT EXISTS shares (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        shared_by UUID NOT NULL REFERENCES users(id),
        shared_with UUID REFERENCES users(id),
        share_link VARCHAR(255) UNIQUE,
        permission_level VARCHAR(50),
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Access logs table
    await client.query(`
      CREATE TABLE IF NOT EXISTS access_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        document_id UUID NOT NULL REFERENCES documents(id),
        action VARCHAR(50),
        ip_address VARCHAR(45),
        user_agent TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // PACS Studies table
    await client.query(`
      CREATE TABLE IF NOT EXISTS pacs_studies (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        study_uid VARCHAR(255) UNIQUE NOT NULL,
        patient_id VARCHAR(255) NOT NULL,
        patient_name VARCHAR(255),
        study_date DATE,
        study_description TEXT,
        storage_path VARCHAR(512) NOT NULL,
        status VARCHAR(50) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // PACS Series table
    await client.query(`
      CREATE TABLE IF NOT EXISTS pacs_series (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        series_uid VARCHAR(255) UNIQUE NOT NULL,
        study_id UUID NOT NULL REFERENCES pacs_studies(id) ON DELETE CASCADE,
        modality VARCHAR(50),
        series_description TEXT,
        storage_path VARCHAR(512) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // PACS Instances table
    await client.query(`
      CREATE TABLE IF NOT EXISTS pacs_instances (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        sop_instance_uid VARCHAR(255) UNIQUE NOT NULL,
        series_id UUID NOT NULL REFERENCES pacs_series(id) ON DELETE CASCADE,
        storage_path VARCHAR(512) NOT NULL,
        size_bytes BIGINT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Notifications queue table
    await client.query(`
      CREATE TABLE IF NOT EXISTS notification_queue (
        id BIGSERIAL PRIMARY KEY,
        event_type VARCHAR(100) NOT NULL,
        user_id UUID REFERENCES users(id),
        document_id UUID REFERENCES documents(id),
        payload JSONB,
        is_processed BOOLEAN DEFAULT false,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Create indexes
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_id);
      CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at);
      CREATE INDEX IF NOT EXISTS idx_shares_document ON shares(document_id);
      CREATE INDEX IF NOT EXISTS idx_access_logs_user ON access_logs(user_id);
      CREATE INDEX IF NOT EXISTS idx_pacs_studies_patient ON pacs_studies(patient_id);
      CREATE INDEX IF NOT EXISTS idx_pacs_series_study ON pacs_series(study_id);
      CREATE INDEX IF NOT EXISTS idx_notification_queue_processed ON notification_queue(is_processed);
    `);

    await client.query('COMMIT');
    logger.info('Database tables initialized successfully');
  } catch (error) {
    await client.query('ROLLBACK');
    logger.error('Failed to initialize database tables', error);
    throw error;
  } finally {
    client.release();
  }
}
