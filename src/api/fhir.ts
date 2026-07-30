import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { query } from '../db/postgres';
import { Logger } from '../utils/logger';

const logger = new Logger();
export const fhirRoutes = Router();

// FHIR Patient resource
fhirRoutes.post('/Patient', async (req: Request, res: Response) => {
  try {
    const { name, identifier, birthDate, gender, contact } = req.body;

    if (!name || !identifier) {
      return res.status(400).json({ error: 'Name and identifier are required' });
    }

    const patientId = uuidv4();

    // Store patient record as document
    await query(
      `INSERT INTO documents (id, name, owner_id, type, storage_path, is_deleted)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        patientId,
        `Patient-${identifier}`,
        req.user!.id,
        'fhir-patient',
        `fhir/patients/${patientId}`,
        false,
      ]
    );

    const fhirResource = {
      resourceType: 'Patient',
      id: patientId,
      identifier: [{ value: identifier }],
      name: [{ text: name }],
      birthDate,
      gender,
      contact: contact || [],
      meta: {
        lastUpdated: new Date().toISOString(),
      },
    };

    res.status(201).json(fhirResource);
  } catch (error) {
    logger.error('FHIR Patient creation error', error);
    res.status(500).json({ error: 'Failed to create patient' });
  }
});

// Get FHIR Patient
fhirRoutes.get('/Patient/:id', async (req: Request, res: Response) => {
  try {
    const { id } = req.params;

    const result = await query(
      `SELECT id, name FROM documents WHERE id = $1 AND type = 'fhir-patient'`,
      [id]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Patient not found' });
    }

    const patient = result.rows[0];

    res.json({
      resourceType: 'Patient',
      id: patient.id,
      name: [{ text: patient.name }],
      meta: {
        lastUpdated: new Date().toISOString(),
      },
    });
  } catch (error) {
    logger.error('FHIR Patient fetch error', error);
    res.status(500).json({ error: 'Failed to fetch patient' });
  }
});

// FHIR Observation resource (for medical measurements)
fhirRoutes.post('/Observation', async (req: Request, res: Response) => {
  try {
    const { status, code, value, subject, effectiveDateTime } = req.body;

    if (!status || !code || !value) {
      return res.status(400).json({ error: 'status, code, and value are required' });
    }

    const observationId = uuidv4();

    await query(
      `INSERT INTO documents (id, name, owner_id, type, storage_path, is_deleted)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        observationId,
        `Observation-${code}`,
        req.user!.id,
        'fhir-observation',
        `fhir/observations/${observationId}`,
        false,
      ]
    );

    const fhirResource = {
      resourceType: 'Observation',
      id: observationId,
      status,
      code: { coding: [{ code }] },
      subject: subject || null,
      effectiveDateTime: effectiveDateTime || new Date().toISOString(),
      value: { value },
      meta: {
        lastUpdated: new Date().toISOString(),
      },
    };

    res.status(201).json(fhirResource);
  } catch (error) {
    logger.error('FHIR Observation creation error', error);
    res.status(500).json({ error: 'Failed to create observation' });
  }
});

// FHIR Condition resource
fhirRoutes.post('/Condition', async (req: Request, res: Response) => {
  try {
    const { code, clinicalStatus, subject, recordedDate } = req.body;

    if (!code || !clinicalStatus) {
      return res.status(400).json({ error: 'code and clinicalStatus are required' });
    }

    const conditionId = uuidv4();

    await query(
      `INSERT INTO documents (id, name, owner_id, type, storage_path, is_deleted)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        conditionId,
        `Condition-${code}`,
        req.user!.id,
        'fhir-condition',
        `fhir/conditions/${conditionId}`,
        false,
      ]
    );

    const fhirResource = {
      resourceType: 'Condition',
      id: conditionId,
      code: { coding: [{ code }] },
      clinicalStatus: { coding: [{ code: clinicalStatus }] },
      subject: subject || null,
      recordedDate: recordedDate || new Date().toISOString(),
      meta: {
        lastUpdated: new Date().toISOString(),
      },
    };

    res.status(201).json(fhirResource);
  } catch (error) {
    logger.error('FHIR Condition creation error', error);
    res.status(500).json({ error: 'Failed to create condition' });
  }
});

// FHIR search (simplified implementation)
fhirRoutes.get('/:resourceType', async (req: Request, res: Response) => {
  try {
    const { resourceType } = req.params;
    const { limit = 50, offset = 0 } = req.query;

    const fhirType = `fhir-${resourceType.toLowerCase()}`;

    const result = await query(
      `SELECT id, name FROM documents
       WHERE type = $1 AND owner_id = $2
       ORDER BY created_at DESC
       LIMIT $3 OFFSET $4`,
      [fhirType, req.user!.id, limit, offset]
    );

    res.json({
      resourceType: 'Bundle',
      type: 'searchset',
      total: result.rows.length,
      entry: result.rows.map((row: any) => ({
        resource: {
          resourceType,
          id: row.id,
          name: row.name,
        },
      })),
    });
  } catch (error) {
    logger.error('FHIR search error', error);
    res.status(500).json({ error: 'Search failed' });
  }
});

// FHIR Metadata (Capability Statement)
fhirRoutes.get('/', (req: Request, res: Response) => {
  res.json({
    resourceType: 'CapabilityStatement',
    status: 'active',
    date: new Date().toISOString(),
    kind: 'instance',
    software: {
      name: 'Distributed SharePoint System - FHIR',
      version: '1.0.0',
    },
    implementation: {
      description: 'DSS FHIR Server',
      url: process.env.FHIR_BASE_URL || 'http://localhost:3000/fhir',
    },
    fhirVersion: process.env.FHIR_VERSION || 'R4',
    format: ['application/fhir+json'],
    rest: [
      {
        mode: 'server',
        resource: [
          {
            type: 'Patient',
            interaction: [{ code: 'create' }, { code: 'read' }, { code: 'search-type' }],
          },
          {
            type: 'Observation',
            interaction: [{ code: 'create' }, { code: 'read' }, { code: 'search-type' }],
          },
          {
            type: 'Condition',
            interaction: [{ code: 'create' }, { code: 'read' }, { code: 'search-type' }],
          },
        ],
      },
    ],
  });
});
