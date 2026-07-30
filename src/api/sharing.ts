import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { query } from '../db/postgres';
import { Logger } from '../utils/logger';
import { getNotificationService } from '../notifications/unix-notification-service';

const logger = new Logger();
export const sharingRoutes = Router();

// Share document with user
sharingRoutes.post('/:documentId/share', async (req: Request, res: Response) => {
  try {
    const { documentId } = req.params;
    const { sharedWithId, permissionLevel, expiresAt } = req.body;
    const userId = req.user!.id;

    if (!sharedWithId || !permissionLevel) {
      return res.status(400).json({ error: 'Missing shared user or permission level' });
    }

    // Verify document ownership
    const docResult = await query(
      `SELECT id FROM documents WHERE id = $1 AND owner_id = $2`,
      [documentId, userId]
    );

    if (docResult.rows.length === 0) {
      return res.status(404).json({ error: 'Document not found' });
    }

    const shareId = uuidv4();
    await query(
      `INSERT INTO shares (id, document_id, shared_by, shared_with, permission_level, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [shareId, documentId, userId, sharedWithId, permissionLevel, expiresAt || null]
    );

    const notificationService = getNotificationService();
    await notificationService.notify({
      id: uuidv4(),
      type: 'document_shared',
      userId: sharedWithId,
      documentId,
      timestamp: Date.now(),
      payload: {
        sharedBy: userId,
        permissionLevel,
      },
    });

    logger.info(`Document ${documentId} shared with user ${sharedWithId}`);

    res.status(201).json({ shareId, documentId, sharedWithId, permissionLevel });
  } catch (error) {
    logger.error('Document sharing error', error);
    res.status(500).json({ error: 'Failed to share document' });
  }
});

// Create public share link
sharingRoutes.post('/:documentId/public-share', async (req: Request, res: Response) => {
  try {
    const { documentId } = req.params;
    const { permissionLevel, expiresAt } = req.body;
    const userId = req.user!.id;

    // Verify document ownership
    const docResult = await query(
      `SELECT id FROM documents WHERE id = $1 AND owner_id = $2`,
      [documentId, userId]
    );

    if (docResult.rows.length === 0) {
      return res.status(404).json({ error: 'Document not found' });
    }

    const shareLink = uuidv4().replace(/-/g, '').substring(0, 16);
    const shareId = uuidv4();

    await query(
      `INSERT INTO shares (id, document_id, shared_by, share_link, permission_level, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [shareId, documentId, userId, shareLink, permissionLevel || 'view', expiresAt || null]
    );

    logger.info(`Public share link created for document ${documentId}`);

    res.status(201).json({
      shareId,
      documentId,
      shareLink,
      shareUrl: `/api/v1/sharing/link/${shareLink}`,
      permissionLevel,
    });
  } catch (error) {
    logger.error('Public share creation error', error);
    res.status(500).json({ error: 'Failed to create public share' });
  }
});

// Access document via share link (no auth required)
sharingRoutes.get('/link/:shareLink/download', async (req: Request, res: Response) => {
  try {
    const { shareLink } = req.params;

    const shareResult = await query(
      `SELECT s.id, s.document_id, s.permission_level, s.expires_at, d.storage_path, d.name
       FROM shares s
       JOIN documents d ON s.document_id = d.id
       WHERE s.share_link = $1 AND d.is_deleted = false`,
      [shareLink]
    );

    if (shareResult.rows.length === 0) {
      return res.status(404).json({ error: 'Share link not found' });
    }

    const share = shareResult.rows[0];

    // Check expiration
    if (share.expires_at && new Date(share.expires_at) < new Date()) {
      return res.status(403).json({ error: 'Share link has expired' });
    }

    // Check permission
    if (!['view', 'download', 'edit'].includes(share.permission_level)) {
      return res.status(403).json({ error: 'Insufficient permissions' });
    }

    // Download from storage
    const { getStorageLayer } = require('../storage/storage-layer');
    const storage = getStorageLayer();
    const buffer = await storage.download(share.storage_path);

    res.setHeader('Content-Disposition', `attachment; filename="${share.name}"`);
    res.send(buffer);
  } catch (error) {
    logger.error('Share link download error', error);
    res.status(500).json({ error: 'Download failed' });
  }
});

// Get document shares
sharingRoutes.get('/:documentId/shares', async (req: Request, res: Response) => {
  try {
    const { documentId } = req.params;
    const userId = req.user!.id;

    // Verify ownership
    await query(
      `SELECT id FROM documents WHERE id = $1 AND owner_id = $2`,
      [documentId, userId]
    );

    const result = await query(
      `SELECT id, shared_with, share_link, permission_level, expires_at, created_at
       FROM shares WHERE document_id = $1
       ORDER BY created_at DESC`,
      [documentId]
    );

    res.json(result.rows);
  } catch (error) {
    logger.error('Shares fetch error', error);
    res.status(500).json({ error: 'Failed to fetch shares' });
  }
});

// Revoke share
sharingRoutes.delete('/:documentId/shares/:shareId', async (req: Request, res: Response) => {
  try {
    const { documentId, shareId } = req.params;
    const userId = req.user!.id;

    // Verify ownership
    const docResult = await query(
      `SELECT id FROM documents WHERE id = $1 AND owner_id = $2`,
      [documentId, userId]
    );

    if (docResult.rows.length === 0) {
      return res.status(403).json({ error: 'Unauthorized' });
    }

    const result = await query(
      `DELETE FROM shares WHERE id = $1 RETURNING id`,
      [shareId]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Share not found' });
    }

    logger.info(`Share revoked: ${shareId}`);

    res.json({ message: 'Share revoked' });
  } catch (error) {
    logger.error('Share revocation error', error);
    res.status(500).json({ error: 'Failed to revoke share' });
  }
});
