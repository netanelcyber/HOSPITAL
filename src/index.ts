import express from 'express';
import cors from 'cors';
import { setupDatabase } from './db/postgres';
import { setupRedis } from './cache/redis';
import { initNotificationService } from './notifications/unix-notification-service';
import { setupStorageLayer } from './storage/storage-layer';
import { apiRoutes } from './api/routes';
import { Logger } from './utils/logger';
import { config } from './config';
import { createAPIGateway } from './security/api-gateway';
import { createNetworkSecurityLayer, createNetworkSegmentation } from './security/network-security';

const app = express();
const logger = new Logger();

async function startup() {
  try {
    logger.info('Starting Distributed SharePoint System...');

    // Initialize Security Layer
    logger.info('Initializing security layer...');
    const apiGateway = createAPIGateway({
      enableRateLimit: true,
      enableDdosProtection: true,
      trustedProxies: ['127.0.0.1', '::1'],
    });

    const networkSecurity = createNetworkSecurityLayer({
      enableTls: config.environment === 'production',
      minTlsVersion: 'TLSv1.2',
    });

    const networkSegmentation = createNetworkSegmentation();

    // Setup network segments
    networkSegmentation.addSegment('api', {
      vlan: 100,
      subnet: '10.0.1.0/24',
      gateway: '10.0.1.1',
      rules: [
        {
          name: 'allow-db-access',
          allowedSegments: ['database'],
          allowedPorts: [5432],
          protocol: 'tcp',
          action: 'allow',
        },
        {
          name: 'allow-cache-access',
          allowedSegments: ['cache'],
          allowedPorts: [6379],
          protocol: 'tcp',
          action: 'allow',
        },
      ],
    });

    networkSegmentation.addSegment('database', {
      vlan: 101,
      subnet: '10.0.2.0/24',
      gateway: '10.0.2.1',
    });

    networkSegmentation.addSegment('cache', {
      vlan: 102,
      subnet: '10.0.3.0/24',
      gateway: '10.0.3.1',
    });

    networkSegmentation.addSegment('storage', {
      vlan: 103,
      subnet: '10.0.4.0/24',
      gateway: '10.0.4.1',
    });

    // Register internal services
    networkSecurity.registerService('api', {
      host: 'localhost',
      port: 3000,
      protocol: 'https',
      rateLimit: 1000,
      timeout: 30000,
    });

    networkSecurity.registerService('database', {
      host: 'postgres',
      port: 5432,
      protocol: 'tcp',
      timeout: 10000,
    });

    networkSecurity.registerService('cache', {
      host: 'redis',
      port: 6379,
      protocol: 'tcp',
      timeout: 5000,
    });

    // Security Middleware
    logger.info('Applying security middleware...');

    // Apply DDoS protection
    app.use(apiGateway.ddosProtectionMiddleware());

    // Apply rate limiting
    app.use('/api/', apiGateway.createRateLimiter(15 * 60 * 1000, 100)); // 100 requests per 15 minutes

    // Apply request validation
    app.use(apiGateway.validateRequestMiddleware());

    // Apply security headers
    app.use(apiGateway.responseSecurityMiddleware());

    // CORS configuration
    app.use(
      cors({
        origin: process.env.ALLOWED_ORIGINS?.split(',') || ['http://localhost:3000'],
        credentials: true,
        methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        allowedHeaders: ['Content-Type', 'Authorization', 'X-Service-Auth'],
      })
    );

    app.use(express.json({ limit: '50mb' }));
    app.use(express.urlencoded({ limit: '50mb', extended: true }));

    // Start cleanup task
    apiGateway.startCleanup();

    // Initialize core services
    logger.info('Initializing database...');
    await setupDatabase();

    logger.info('Initializing cache layer...');
    await setupRedis();

    logger.info('Initializing storage layer...');
    await setupStorageLayer();

    logger.info('Initializing UNIX notification service...');
    const notificationService = initNotificationService();

    // Make services available to request handlers
    app.use((req, res, next) => {
      (req as any).notificationService = notificationService;
      (req as any).apiGateway = apiGateway;
      (req as any).networkSecurity = networkSecurity;
      next();
    });

    // Routes
    app.use('/api/v1', apiRoutes);

    // Security status endpoint
    app.get('/security/status', (req, res) => {
      res.json({
        api: apiGateway.getStats(),
        network: networkSecurity.getSecurityStatus(),
        segmentation: networkSegmentation.getSegmentationStatus(),
      });
    });

    // Health check
    app.get('/health', (req, res) => {
      res.json({ status: 'ok', timestamp: new Date().toISOString() });
    });

    // Start server
    const PORT = config.port || 3000;
    const server = networkSecurity.createSecureServer(app, PORT);

    server.listen(PORT, () => {
      logger.info(`Server running on port ${PORT}`);
      logger.info(`Security status available at /security/status`);
    });

  } catch (error) {
    logger.error('Startup failed', error);
    process.exit(1);
  }
}

startup();
