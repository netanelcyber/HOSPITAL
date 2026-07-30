import dotenv from 'dotenv';

dotenv.config();

export const config = {
  port: parseInt(process.env.PORT || '3000'),

  database: {
    host: process.env.DB_HOST || 'localhost',
    port: parseInt(process.env.DB_PORT || '5432'),
    username: process.env.DB_USER || 'postgres',
    password: process.env.DB_PASSWORD || '',
    database: process.env.DB_NAME || 'dss',
  },

  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: parseInt(process.env.REDIS_PORT || '6379'),
    password: process.env.REDIS_PASSWORD,
  },

  storage: {
    type: process.env.STORAGE_TYPE || 's3',
    s3: {
      endpoint: process.env.S3_ENDPOINT || 'http://localhost:9000',
      accessKey: process.env.S3_ACCESS_KEY || 'minioadmin',
      secretKey: process.env.S3_SECRET_KEY || 'minioadmin',
      bucket: process.env.S3_BUCKET || 'dss-storage',
      region: process.env.S3_REGION || 'us-east-1',
    },
  },

  notifications: {
    socketPath: process.env.NOTIFICATION_SOCKET || '/tmp/dss-notification.sock',
    queuePath: process.env.NOTIFICATION_QUEUE || '/tmp/dss-notification-queue',
    enableSignals: process.env.ENABLE_SIGNAL_NOTIFICATIONS !== 'false',
    enableSockets: process.env.ENABLE_SOCKET_NOTIFICATIONS !== 'false',
    enableQueues: process.env.ENABLE_QUEUE_NOTIFICATIONS !== 'false',
  },

  jwt: {
    secret: process.env.JWT_SECRET || 'dev-secret-key',
    expiresIn: process.env.JWT_EXPIRES_IN || '24h',
  },

  pacs: {
    enabled: process.env.PACS_ENABLED !== 'false',
    dicomPort: parseInt(process.env.DICOM_PORT || '11112'),
    dicomAET: process.env.DICOM_AET || 'DSS_NODE',
  },

  fhir: {
    enabled: process.env.FHIR_ENABLED === 'true',
    version: process.env.FHIR_VERSION || 'R4',
    baseUrl: process.env.FHIR_BASE_URL || 'http://localhost:3000/fhir',
  },

  environment: process.env.NODE_ENV || 'development',
};
