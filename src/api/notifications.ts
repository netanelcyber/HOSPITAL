import { Router, Request, Response } from 'express';
import { Server as SocketIOServer } from 'socket.io';
import { getNotificationService } from '../notifications/unix-notification-service';
import { query } from '../db/postgres';
import { Logger } from '../utils/logger';

const logger = new Logger();
export const notificationRoutes = Router();

// WebSocket subscriptions (will be managed by socket.io middleware)
notificationRoutes.get('/subscribe', async (req: Request, res: Response) => {
  try {
    const userId = req.user!.id;
    const { eventTypes = '*' } = req.query;

    const notificationService = getNotificationService();

    if (eventTypes === '*') {
      notificationService.subscribeClient(userId, ['*']);
    } else {
      const types = (eventTypes as string).split(',');
      notificationService.subscribeClient(userId, types);
    }

    logger.info(`User ${userId} subscribed to notifications`);

    res.json({
      status: 'subscribed',
      userId,
      eventTypes: eventTypes === '*' ? 'all' : eventTypes,
    });
  } catch (error) {
    logger.error('Subscription error', error);
    res.status(500).json({ error: 'Failed to subscribe' });
  }
});

// Get notification stats
notificationRoutes.get('/stats', (req: Request, res: Response) => {
  try {
    const notificationService = getNotificationService();
    const stats = notificationService.getStats();

    res.json(stats);
  } catch (error) {
    logger.error('Stats error', error);
    res.status(500).json({ error: 'Failed to fetch stats' });
  }
});

// Get recent notifications for user
notificationRoutes.get('/history', async (req: Request, res: Response) => {
  try {
    const userId = req.user!.id;
    const { limit = 50, offset = 0 } = req.query;

    const result = await query(
      `SELECT id, event_type, document_id, payload, created_at
       FROM notification_queue
       WHERE (user_id = $1 OR user_id IS NULL)
       AND is_processed = true
       ORDER BY created_at DESC
       LIMIT $2 OFFSET $3`,
      [userId, limit, offset]
    );

    res.json({
      notifications: result.rows,
      limit,
      offset,
    });
  } catch (error) {
    logger.error('History fetch error', error);
    res.status(500).json({ error: 'Failed to fetch notification history' });
  }
});

// Clear notifications
notificationRoutes.post('/clear', async (req: Request, res: Response) => {
  try {
    const userId = req.user!.id;

    await query(
      `UPDATE notification_queue
       SET is_processed = true
       WHERE user_id = $1 AND is_processed = false`,
      [userId]
    );

    res.json({ message: 'Notifications cleared' });
  } catch (error) {
    logger.error('Clear notifications error', error);
    res.status(500).json({ error: 'Failed to clear notifications' });
  }
});

// WebSocket handler (to be used with socket.io)
export function setupNotificationSocket(io: SocketIOServer) {
  const notificationService = getNotificationService();

  io.on('connection', (socket) => {
    const userId = socket.handshake.auth.userId;

    if (!userId) {
      socket.disconnect();
      return;
    }

    logger.info(`WebSocket connection established for user ${userId}`);

    // Subscribe to user's notifications
    const handleNotification = (notification: any) => {
      socket.emit('notification', notification);
    };

    notificationService.on(`user:${userId}`, handleNotification);

    socket.on('disconnect', () => {
      logger.info(`WebSocket connection closed for user ${userId}`);
      notificationService.removeListener(`user:${userId}`, handleNotification);
    });

    socket.on('subscribe', (data) => {
      const { eventTypes } = data;
      notificationService.subscribeClient(userId, eventTypes);
      socket.emit('subscribed', { eventTypes });
    });
  });
}
