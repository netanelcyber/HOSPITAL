import { Router, Request, Response } from 'express';
import multer from 'multer';
import { v4 as uuidv4 } from 'uuid';
import crypto from 'crypto';
import { query } from '../db/postgres';
import { getStorageLayer } from '../storage/storage-layer';
import { cacheInvalidatePattern, cacheSet, cacheGet } from '../cache/redis';
import { getNotificationService } from '../notifications/unix-notification-service';
import { Logger } from '../utils/logger';

const logger = new Logger();
export const documentRoutes = Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 500 * 1024 * 1024 }, // 500MB
});

interface FolderNode {
  id: string;
  name: string;
  parent_id?: string;
  owner_id: string;
  is_folder: boolean;
  children?: FolderNode[];
}

// Create folder
documentRoutes.post('/folders', async (req: Request, res: Response) => {
  try {
    const { name, parentId } = req.body;
    const userId = req.user!.id;

    if (!name) {
      return res.status(400).json({ error: 'Folder name required' });
    }

    const folderId = uuidv4();

    await query(
      `INSERT INTO documents (id, name, owner_id, type, storage_path, is_deleted)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [folderId, name, userId, 'folder', `folders/${folderId}`, false]
    );

    // Update metadata with parent relationship
    if (parentId) {
      await query(
        `UPDATE documents SET storage_path = $1 WHERE id = $2`,
        [`folders/${parentId}/${folderId}`, folderId]
      );
    }

    cacheInvalidatePattern(`user:${userId}:documents:*`);

    const notificationService = getNotificationService();
    await notificationService.notify({
      id: uuidv4(),
      type: 'folder_created',
      userId,
      documentId: folderId,
      timestamp: Date.now(),
      payload: { name, parentId },
    });

    res.status(201).json({ id: folderId, name, type: 'folder', parentId });
  } catch (error) {
    logger.error('Folder creation error', error);
    res.status(500).json({ error: 'Failed to create folder' });
  }
});

// Upload document
documentRoutes.post('/upload', upload.single('file'), async (req: Request, res: Response) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No file provided' });
    }

    const { parentId, description } = req.body;
    const userId = req.user!.id;
    const documentId = uuidv4();

    const buffer = req.file.buffer;
    const checksum = crypto.createHash('sha256').update(buffer).digest('hex');

    // Determine storage path
    let storagePath = `documents/${userId}/${documentId}`;
    if (parentId) {
      storagePath = `documents/${userId}/${parentId}/${documentId}`;
    }

    // Upload to storage layer
    const storage = getStorageLayer();
    await storage.upload(storagePath, buffer, {
      originalName: req.file.originalname,
      contentType: req.file.mimetype,
      userId,
      checksum,
    });

    // Save metadata
    await query(
      `INSERT INTO documents (id, name, owner_id, type, storage_path, size_bytes, mime_type, checksum)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
      [
        documentId,
        req.file.originalname,
        userId,
        'document',
        storagePath,
        buffer.length,
        req.file.mimetype,
        checksum,
      ]
    );

    // Create initial version
    await query(
      `INSERT INTO document_versions (id, document_id, version_number, storage_path, created_by, change_description)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [uuidv4(), documentId, 1, storagePath, userId, description || 'Initial version']
    );

    cacheInvalidatePattern(`user:${userId}:documents:*`);

    const notificationService = getNotificationService();
    await notificationService.notify({
      id: uuidv4(),
      type: 'document_uploaded',
      userId,
      documentId,
      timestamp: Date.now(),
      payload: {
        name: req.file.originalname,
        size: buffer.length,
        parentId,
      },
    });

    logger.info(`Document uploaded: ${documentId} by user ${userId}`);

    res.status(201).json({
      id: documentId,
      name: req.file.originalname,
      size: buffer.length,
      type: 'document',
      checksum,
      parentId,
    });
  } catch (error) {
    logger.error('Document upload error', error);
    res.status(500).json({ error: 'Upload failed' });
  }
});

// Get document tree (nested structure)
documentRoutes.get('/tree', async (req: Request, res: Response) => {
  try {
    const userId = req.user!.id;

    const cached = await cacheGet(`user:${userId}:documents:tree`);
    if (cached) {
      return res.json(cached);
    }

    // Get all user's documents
    const result = await query(
      `SELECT id, name, type, storage_path, created_at
       FROM documents
       WHERE owner_id = $1 AND is_deleted = false
       ORDER BY name`,
      [userId]
    );

    // Build tree structure
    const tree = buildTree(result.rows);

    cacheSet(`user:${userId}:documents:tree`, tree, 600);

    res.json(tree);
  } catch (error) {
    logger.error('Document tree fetch error', error);
    res.status(500).json({ error: 'Failed to fetch documents' });
  }
});

// Get single document
documentRoutes.get('/:documentId', async (req: Request, res: Response) => {
  try {
    const { documentId } = req.params;
    const userId = req.user!.id;

    const result = await query(
      `SELECT id, name, type, size_bytes, mime_type, checksum, created_at, updated_at
       FROM documents
       WHERE id = $1 AND owner_id = $2 AND is_deleted = false`,
      [documentId, userId]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Document not found' });
    }

    res.json(result.rows[0]);
  } catch (error) {
    logger.error('Document fetch error', error);
    res.status(500).json({ error: 'Failed to fetch document' });
  }
});

// Download document
documentRoutes.get('/:documentId/download', async (req: Request, res: Response) => {
  try {
    const { documentId } = req.params;
    const userId = req.user!.id;

    // Check permissions
    const docResult = await query(
      `SELECT name, storage_path, mime_type, size_bytes
       FROM documents
       WHERE id = $1 AND owner_id = $2 AND is_deleted = false`,
      [documentId, userId]
    );

    if (docResult.rows.length === 0) {
      return res.status(404).json({ error: 'Document not found' });
    }

    const doc = docResult.rows[0];

    // Log access
    await query(
      `INSERT INTO access_logs (id, user_id, document_id, action, ip_address)
       VALUES ($1, $2, $3, $4, $5)`,
      [uuidv4(), userId, documentId, 'download', req.ip]
    );

    // Download from storage
    const storage = getStorageLayer();
    const buffer = await storage.download(doc.storage_path);

    res.setHeader('Content-Disposition', `attachment; filename="${doc.name}"`);
    res.setHeader('Content-Type', doc.mime_type || 'application/octet-stream');
    res.setHeader('Content-Length', buffer.length);

    res.send(buffer);
  } catch (error) {
    logger.error('Document download error', error);
    res.status(500).json({ error: 'Download failed' });
  }
});

// Delete document (soft delete)
documentRoutes.delete('/:documentId', async (req: Request, res: Response) => {
  try {
    const { documentId } = req.params;
    const userId = req.user!.id;

    const result = await query(
      `UPDATE documents
       SET is_deleted = true, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND owner_id = $2
       RETURNING id`,
      [documentId, userId]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Document not found' });
    }

    cacheInvalidatePattern(`user:${userId}:documents:*`);

    const notificationService = getNotificationService();
    await notificationService.notify({
      id: uuidv4(),
      type: 'document_deleted',
      userId,
      documentId,
      timestamp: Date.now(),
      payload: {},
    });

    res.json({ message: 'Document deleted' });
  } catch (error) {
    logger.error('Document deletion error', error);
    res.status(500).json({ error: 'Failed to delete document' });
  }
});

// Get document versions
documentRoutes.get('/:documentId/versions', async (req: Request, res: Response) => {
  try {
    const { documentId } = req.params;
    const userId = req.user!.id;

    // Verify ownership
    await query(
      `SELECT id FROM documents WHERE id = $1 AND owner_id = $2`,
      [documentId, userId]
    );

    const result = await query(
      `SELECT id, version_number, created_by, change_description, created_at
       FROM document_versions
       WHERE document_id = $1
       ORDER BY version_number DESC`,
      [documentId]
    );

    res.json(result.rows);
  } catch (error) {
    logger.error('Version fetch error', error);
    res.status(500).json({ error: 'Failed to fetch versions' });
  }
});

// Helper function to build nested tree structure
function buildTree(documents: any[]): FolderNode[] {
  const map: Record<string, FolderNode> = {};
  const roots: FolderNode[] = [];

  // Create all nodes
  documents.forEach((doc) => {
    map[doc.id] = {
      id: doc.id,
      name: doc.name,
      owner_id: doc.owner_id,
      is_folder: doc.type === 'folder',
      children: [],
    };
  });

  // Build hierarchy
  documents.forEach((doc) => {
    const path = doc.storage_path.split('/');
    if (path.length <= 2) {
      // Root level
      roots.push(map[doc.id]);
    } else {
      // Find parent
      for (const id in map) {
        if (doc.storage_path.includes(`/${id}/`)) {
          if (!map[id].children) {
            map[id].children = [];
          }
          map[id].children!.push(map[doc.id]);
          break;
        }
      }
    }
  });

  return roots;
}
