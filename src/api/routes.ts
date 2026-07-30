import { Router } from 'express';
import { authRoutes } from './auth';
import { documentRoutes } from './documents';
import { pacsRoutes } from './pacs';
import { sharingRoutes } from './sharing';
import { notificationRoutes } from './notifications';
import { fhirRoutes } from './fhir';
import { vmRoutes } from './vm';
import { authMiddleware } from './middleware/auth';

export const apiRoutes = Router();

// Public routes
apiRoutes.use('/auth', authRoutes);

// Protected routes
apiRoutes.use('/documents', authMiddleware, documentRoutes);
apiRoutes.use('/pacs', authMiddleware, pacsRoutes);
apiRoutes.use('/sharing', authMiddleware, sharingRoutes);
apiRoutes.use('/notifications', authMiddleware, notificationRoutes);
apiRoutes.use('/vms', authMiddleware, vmRoutes);

// Optional FHIR routes
if (process.env.FHIR_ENABLED === 'true') {
  apiRoutes.use('/fhir', fhirRoutes);
}

// Status endpoints
apiRoutes.get('/status', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});
