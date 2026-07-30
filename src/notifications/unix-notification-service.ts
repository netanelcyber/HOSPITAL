import { EventEmitter } from 'events';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as net from 'net';
import { Logger } from '../utils/logger';
import { config } from '../config';

interface Notification {
  id: string;
  type: string;
  userId?: string;
  documentId?: string;
  timestamp: number;
  payload: any;
}

export class UnixNotificationService extends EventEmitter {
  private logger = new Logger();
  private socketServer?: net.Server;
  private fifoPath?: string;
  private subscribers: Map<string, Set<string>> = new Map(); // userId -> Set of event types
  private queueBuffer: Notification[] = [];

  async initialize() {
    this.logger.info('Initializing UNIX notification service');

    // Setup signal handlers
    this.setupSignalHandlers();

    // Setup Unix domain socket
    if (config.notifications.enableSockets) {
      await this.setupUnixSocket();
    }

    // Setup FIFO queue
    if (config.notifications.enableQueues) {
      await this.setupFifoQueue();
    }

    // Setup message queue processing
    this.startQueueProcessor();

    this.logger.info('UNIX notification service initialized');
  }

  private setupSignalHandlers() {
    // Handle SIGUSR1 for notifications
    process.on('SIGUSR1', () => {
      this.logger.debug('Received SIGUSR1 - processing notifications');
      this.processQueueBuffer();
    });

    // Handle SIGUSR2 for health check
    process.on('SIGUSR2', () => {
      this.logger.debug('Received SIGUSR2 - health check');
      this.emit('health-check', {
        status: 'ok',
        queueSize: this.queueBuffer.length,
        subscriberCount: this.subscribers.size,
      });
    });
  }

  private async setupUnixSocket() {
    const socketPath = config.notifications.socketPath;

    // Clean up existing socket if it exists
    try {
      if (fs.existsSync(socketPath)) {
        fs.unlinkSync(socketPath);
      }
    } catch (error) {
      this.logger.warn('Could not remove existing socket', error);
    }

    this.socketServer = net.createServer((socket) => {
      this.handleSocketConnection(socket);
    });

    this.socketServer.listen(socketPath, () => {
      this.logger.info(`Unix socket server listening at ${socketPath}`);
      // Set permissions so other processes can connect
      fs.chmodSync(socketPath, 0o666);
    });

    this.socketServer.on('error', (error) => {
      this.logger.error('Unix socket error', error);
    });
  }

  private handleSocketConnection(socket: net.Socket) {
    const clientId = `socket-${Date.now()}`;
    this.logger.debug(`New socket connection: ${clientId}`);

    socket.on('data', (data) => {
      try {
        const message = JSON.parse(data.toString());
        if (message.action === 'subscribe') {
          this.subscribeClient(message.userId, message.eventTypes);
          socket.write(JSON.stringify({ status: 'subscribed' }));
        } else if (message.action === 'unsubscribe') {
          this.unsubscribeClient(message.userId);
          socket.write(JSON.stringify({ status: 'unsubscribed' }));
        }
      } catch (error) {
        this.logger.error('Error handling socket message', error);
        socket.write(JSON.stringify({ error: 'Invalid message' }));
      }
    });

    socket.on('end', () => {
      this.logger.debug(`Socket connection closed: ${clientId}`);
    });

    socket.on('error', (error) => {
      this.logger.error(`Socket error: ${clientId}`, error);
    });
  }

  private async setupFifoQueue() {
    const queuePath = config.notifications.queuePath;

    try {
      if (fs.existsSync(queuePath)) {
        fs.unlinkSync(queuePath);
      }

      // Create named pipe using mkfifo via command
      const { execSync } = require('child_process');
      try {
        execSync(`mkfifo ${queuePath}`);
        fs.chmodSync(queuePath, 0o666);
        this.fifoPath = queuePath;
        this.logger.info(`FIFO queue created at ${queuePath}`);
      } catch (error) {
        // mkfifo might not be available on all systems
        this.logger.warn('Could not create FIFO queue', error);
      }
    } catch (error) {
      this.logger.error('Error setting up FIFO', error);
    }
  }

  private startQueueProcessor() {
    // Process queue every 100ms
    setInterval(() => {
      if (this.queueBuffer.length > 0) {
        this.processQueueBuffer();
      }
    }, 100);
  }

  private processQueueBuffer() {
    const batch = this.queueBuffer.splice(0, 100);
    batch.forEach((notification) => {
      this.broadcastNotification(notification);
    });
  }

  async notify(notification: Notification) {
    // Add to queue buffer
    this.queueBuffer.push({
      ...notification,
      id: notification.id || this.generateNotificationId(),
      timestamp: notification.timestamp || Date.now(),
    });

    // For small queues, process immediately
    if (this.queueBuffer.length >= 10) {
      this.processQueueBuffer();
    }

    // Emit internal event
    this.emit('notification', notification);
  }

  private broadcastNotification(notification: Notification) {
    // Check subscribers
    const interestedUsers = this.getInterestedSubscribers(notification);
    interestedUsers.forEach((userId) => {
      this.emit(`user:${userId}`, notification);
    });

    this.logger.debug(`Broadcast notification ${notification.id} to ${interestedUsers.length} users`);
  }

  private getInterestedSubscribers(notification: Notification): string[] {
    const interested: string[] = [];

    this.subscribers.forEach((eventTypes, userId) => {
      if (eventTypes.has(notification.type) || eventTypes.has('*')) {
        interested.push(userId);
      }
    });

    return interested;
  }

  subscribeClient(userId: string, eventTypes: string[]) {
    if (!this.subscribers.has(userId)) {
      this.subscribers.set(userId, new Set());
    }
    eventTypes.forEach((type) => {
      this.subscribers.get(userId)!.add(type);
    });
    this.logger.debug(`User ${userId} subscribed to ${eventTypes.join(', ')}`);
  }

  unsubscribeClient(userId: string) {
    this.subscribers.delete(userId);
    this.logger.debug(`User ${userId} unsubscribed`);
  }

  private generateNotificationId(): string {
    return `notif-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }

  getStats() {
    return {
      queueSize: this.queueBuffer.length,
      subscriberCount: this.subscribers.size,
      socketPath: config.notifications.socketPath,
      fifoPath: this.fifoPath,
    };
  }

  async shutdown() {
    this.logger.info('Shutting down notification service');
    if (this.socketServer) {
      this.socketServer.close();
    }
    if (this.fifoPath && fs.existsSync(this.fifoPath)) {
      fs.unlinkSync(this.fifoPath);
    }
  }
}

let notificationService: UnixNotificationService;

export function initNotificationService(): UnixNotificationService {
  if (!notificationService) {
    notificationService = new UnixNotificationService();
    notificationService.initialize().catch((error) => {
      new Logger().error('Failed to initialize notification service', error);
    });
  }
  return notificationService;
}

export function getNotificationService(): UnixNotificationService {
  if (!notificationService) {
    throw new Error('Notification service not initialized');
  }
  return notificationService;
}
