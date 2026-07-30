import express from 'express';
import cors from 'cors';
import { setupDatabase } from './db/postgres';
import { setupRedis } from './cache/redis';
import { initNotificationService } from './notifications/unix-notification-service';
import { setupStorageLayer } from './storage/storage-layer';
import { apiRoutes } from './api/routes';
import { Logger } from './utils/logger';
import { config } from './config';

const app = express();
const logger = new Logger();

async function startup() {
  try {
    logger.info('Starting Distributed SharePoint System...');

    // Middleware
    app.use(cors());
    app.use(express.json({ limit: '50mb' }));
    app.use(express.urlencoded({ limit: '50mb', extended: true }));

    // Initialize core services
    logger.info('Initializing database...');
    await setupDatabase();

    logger.info('Initializing cache layer...');
    await setupRedis();

    logger.info('Initializing storage layer...');
    await setupStorageLayer();

    logger.info('Initializing UNIX notification service...');
    const notificationService = initNotificationService();

    // Make notification service available to request handlers
    app.use((req, res, next) => {
      (req as any).notificationService = notificationService;
      next();
    });

    // Routes
    app.use('/api/v1', apiRoutes);

    // Health check
    app.get('/health', (req, res) => {
      res.json({ status: 'ok', timestamp: new Date().toISOString() });
    });

    // Start server
    const PORT = config.port || 3000;
    app.listen(PORT, () => {
      logger.info(`Server running on port ${PORT}`);
    });

  } catch (error) {
    logger.error('Startup failed', error);
    process.exit(1);
  }
}

startup();
