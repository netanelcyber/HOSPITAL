import { Router, Request, Response } from 'express';
import multer from 'multer';
import { v4 as uuidv4 } from 'uuid';
import { query } from '../db/postgres';
import { getStorageLayer } from '../storage/storage-layer';
import { getNotificationService } from '../notifications/unix-notification-service';
import { Logger } from '../utils/logger';

const logger = new Logger();
export const pacsRoutes = Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 1024 * 1024 * 1024 }, // 1GB for DICOM files
});

// Upload DICOM study
pacsRoutes.post('/studies/upload', upload.single('dicom'), async (req: Request, res: Response) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No DICOM file provided' });
    }

    const { studyUid, patientId, patientName, studyDate, studyDescription, seriesUid, modality } =
      req.body;

    if (!studyUid || !patientId) {
      return res.status(400).json({ error: 'Missing required DICOM identifiers' });
    }

    // Get or create study
    let studyResult = await query(
      `SELECT id FROM pacs_studies WHERE study_uid = $1`,
      [studyUid]
    );

    let studyId: string;
    if (studyResult.rows.length === 0) {
      studyId = uuidv4();
      await query(
        `INSERT INTO pacs_studies (id, study_uid, patient_id, patient_name, study_date, study_description)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [studyId, studyUid, patientId, patientName || '', studyDate || new Date(), studyDescription || '']
      );
    } else {
      studyId = studyResult.rows[0].id;
    }

    // Get or create series
    let seriesResult = await query(
      `SELECT id FROM pacs_series WHERE series_uid = $1`,
      [seriesUid]
    );

    let seriesId: string;
    if (seriesResult.rows.length === 0) {
      seriesId = uuidv4();
      const seriesPath = `pacs/${studyUid}/${seriesUid}`;
      await query(
        `INSERT INTO pacs_series (id, series_uid, study_id, modality, storage_path)
         VALUES ($1, $2, $3, $4, $5)`,
        [seriesId, seriesUid, studyId, modality || 'CT', seriesPath]
      );
    } else {
      seriesId = seriesResult.rows[0].id;
    }

    // Create instance
    const instanceUid = `${studyUid}.${seriesUid}.${Date.now()}`;
    const instancePath = `pacs/${studyUid}/${seriesUid}/${instanceUid}`;

    // Upload DICOM file
    const storage = getStorageLayer();
    await storage.upload(instancePath, req.file.buffer, {
      sopInstanceUid: instanceUid,
      studyUid,
      seriesUid,
      patientId,
      modality,
    });

    // Save instance metadata
    const instanceId = uuidv4();
    await query(
      `INSERT INTO pacs_instances (id, sop_instance_uid, series_id, storage_path, size_bytes)
       VALUES ($1, $2, $3, $4, $5)`,
      [instanceId, instanceUid, seriesId, instancePath, req.file.buffer.length]
    );

    const notificationService = getNotificationService();
    await notificationService.notify({
      id: uuidv4(),
      type: 'dicom_received',
      userId: req.user!.id,
      documentId: studyId,
      timestamp: Date.now(),
      payload: {
        studyUid,
        patientId,
        seriesUid,
        modality,
      },
    });

    logger.info(`DICOM instance uploaded: ${instanceUid}`);

    res.status(201).json({
      studyId,
      seriesId,
      instanceId,
      studyUid,
      seriesUid,
      instanceUid,
    });
  } catch (error) {
    logger.error('DICOM upload error', error);
    res.status(500).json({ error: 'DICOM upload failed' });
  }
});

// Get studies (with filtering)
pacsRoutes.get('/studies', async (req: Request, res: Response) => {
  try {
    const { patientId, studyDate, modality, limit = 50, offset = 0 } = req.query;

    let whereClause = '1=1';
    const params: any[] = [];

    if (patientId) {
      whereClause += ` AND patient_id = $${params.length + 1}`;
      params.push(patientId);
    }

    if (studyDate) {
      whereClause += ` AND DATE(study_date) = $${params.length + 1}`;
      params.push(studyDate);
    }

    const query_text = `
      SELECT ps.id, ps.study_uid, ps.patient_id, ps.patient_name, ps.study_date,
             COUNT(DISTINCT pser.id) as series_count,
             COUNT(DISTINCT pi.id) as instance_count
      FROM pacs_studies ps
      LEFT JOIN pacs_series pser ON ps.id = pser.study_id
      LEFT JOIN pacs_instances pi ON pser.id = pi.series_id
      WHERE ${whereClause}
      GROUP BY ps.id, ps.study_uid, ps.patient_id, ps.patient_name, ps.study_date
      ORDER BY ps.study_date DESC
      LIMIT $${params.length + 1} OFFSET $${params.length + 2}
    `;

    params.push(limit);
    params.push(offset);

    const result = await query(query_text, params);

    res.json({
      studies: result.rows,
      limit,
      offset,
      total: result.rows.length,
    });
  } catch (error) {
    logger.error('Studies fetch error', error);
    res.status(500).json({ error: 'Failed to fetch studies' });
  }
});

// Get study details with series and instances
pacsRoutes.get('/studies/:studyId', async (req: Request, res: Response) => {
  try {
    const { studyId } = req.params;

    const studyResult = await query(
      `SELECT id, study_uid, patient_id, patient_name, study_date, study_description
       FROM pacs_studies WHERE id = $1`,
      [studyId]
    );

    if (studyResult.rows.length === 0) {
      return res.status(404).json({ error: 'Study not found' });
    }

    const study = studyResult.rows[0];

    const seriesResult = await query(
      `SELECT id, series_uid, modality, series_description, created_at
       FROM pacs_series WHERE study_id = $1
       ORDER BY created_at DESC`,
      [studyId]
    );

    const series = await Promise.all(
      seriesResult.rows.map(async (s: any) => {
        const instancesResult = await query(
          `SELECT id, sop_instance_uid, created_at FROM pacs_instances WHERE series_id = $1`,
          [s.id]
        );
        return {
          ...s,
          instances: instancesResult.rows,
        };
      })
    );

    res.json({
      ...study,
      series,
    });
  } catch (error) {
    logger.error('Study details fetch error', error);
    res.status(500).json({ error: 'Failed to fetch study details' });
  }
});

// Download DICOM instance
pacsRoutes.get('/instances/:instanceId/download', async (req: Request, res: Response) => {
  try {
    const { instanceId } = req.params;

    const result = await query(
      `SELECT id, sop_instance_uid, storage_path FROM pacs_instances WHERE id = $1`,
      [instanceId]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Instance not found' });
    }

    const instance = result.rows[0];

    // Log access
    await query(
      `INSERT INTO access_logs (id, user_id, document_id, action, ip_address)
       VALUES ($1, $2, $3, $4, $5)`,
      [uuidv4(), req.user!.id, instanceId, 'dicom_download', req.ip]
    );

    // Download from storage
    const storage = getStorageLayer();
    const buffer = await storage.download(instance.storage_path);

    res.setHeader('Content-Disposition', `attachment; filename="${instance.sop_instance_uid}.dcm"`);
    res.setHeader('Content-Type', 'application/dicom');
    res.send(buffer);
  } catch (error) {
    logger.error('Instance download error', error);
    res.status(500).json({ error: 'Download failed' });
  }
});

// Get PACS statistics
pacsRoutes.get('/stats', async (req: Request, res: Response) => {
  try {
    const statsResult = await query(`
      SELECT
        COUNT(DISTINCT ps.id) as total_studies,
        COUNT(DISTINCT pser.id) as total_series,
        COUNT(DISTINCT pi.id) as total_instances,
        SUM(pi.size_bytes) as total_size_bytes,
        COUNT(DISTINCT ps.patient_id) as unique_patients
      FROM pacs_studies ps
      LEFT JOIN pacs_series pser ON ps.id = pser.study_id
      LEFT JOIN pacs_instances pi ON pser.id = pi.series_id
    `);

    res.json(statsResult.rows[0]);
  } catch (error) {
    logger.error('PACS stats error', error);
    res.status(500).json({ error: 'Failed to fetch statistics' });
  }
});
