import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { getVMOrchestrator } from '../vm/vm-orchestrator';
import { Logger } from '../utils/logger';

const logger = new Logger();
export const vmRoutes = Router();

// Create VM
vmRoutes.post('/', async (req: Request, res: Response) => {
  try {
    const { name, cpu, memory, disk, hypervisor = 'virtualbox', network } = req.body;

    if (!name || !cpu || !memory) {
      return res.status(400).json({ error: 'Missing required VM configuration' });
    }

    const orchestrator = getVMOrchestrator();
    const vmId = uuidv4();

    const vmState = await orchestrator.createVM({
      id: vmId,
      name,
      cpu,
      memory,
      disk: disk || 20,
      hypervisor: (hypervisor as any) || 'virtualbox',
      network: network || { type: 'nat' },
    });

    logger.info(`VM created: ${vmId}`);

    res.status(201).json(vmState);
  } catch (error) {
    logger.error('VM creation error', error);
    res.status(500).json({ error: 'Failed to create VM' });
  }
});

// List VMs
vmRoutes.get('/', (req: Request, res: Response) => {
  try {
    const orchestrator = getVMOrchestrator();
    const vms = orchestrator.listVMs();

    res.json(vms);
  } catch (error) {
    logger.error('VMs list error', error);
    res.status(500).json({ error: 'Failed to list VMs' });
  }
});

// Get VM details
vmRoutes.get('/:vmId', (req: Request, res: Response) => {
  try {
    const { vmId } = req.params;
    const orchestrator = getVMOrchestrator();
    const vmState = orchestrator.getVMState(vmId);

    if (!vmState) {
      return res.status(404).json({ error: 'VM not found' });
    }

    res.json(vmState);
  } catch (error) {
    logger.error('VM details error', error);
    res.status(500).json({ error: 'Failed to fetch VM' });
  }
});

// Start VM
vmRoutes.post('/:vmId/start', async (req: Request, res: Response) => {
  try {
    const { vmId } = req.params;
    const orchestrator = getVMOrchestrator();

    await orchestrator.startVM(vmId);
    const vmState = orchestrator.getVMState(vmId);

    logger.info(`VM started: ${vmId}`);

    res.json(vmState);
  } catch (error) {
    logger.error('VM start error', error);
    res.status(500).json({ error: 'Failed to start VM' });
  }
});

// Stop VM
vmRoutes.post('/:vmId/stop', async (req: Request, res: Response) => {
  try {
    const { vmId } = req.params;
    const orchestrator = getVMOrchestrator();

    await orchestrator.stopVM(vmId);
    const vmState = orchestrator.getVMState(vmId);

    logger.info(`VM stopped: ${vmId}`);

    res.json(vmState);
  } catch (error) {
    logger.error('VM stop error', error);
    res.status(500).json({ error: 'Failed to stop VM' });
  }
});

// Pause VM
vmRoutes.post('/:vmId/pause', async (req: Request, res: Response) => {
  try {
    const { vmId } = req.params;
    const orchestrator = getVMOrchestrator();

    await orchestrator.pauseVM(vmId);
    const vmState = orchestrator.getVMState(vmId);

    res.json(vmState);
  } catch (error) {
    logger.error('VM pause error', error);
    res.status(500).json({ error: 'Failed to pause VM' });
  }
});

// Resume VM
vmRoutes.post('/:vmId/resume', async (req: Request, res: Response) => {
  try {
    const { vmId } = req.params;
    const orchestrator = getVMOrchestrator();

    await orchestrator.resumeVM(vmId);
    const vmState = orchestrator.getVMState(vmId);

    res.json(vmState);
  } catch (error) {
    logger.error('VM resume error', error);
    res.status(500).json({ error: 'Failed to resume VM' });
  }
});

// Delete VM
vmRoutes.delete('/:vmId', async (req: Request, res: Response) => {
  try {
    const { vmId } = req.params;
    const orchestrator = getVMOrchestrator();

    await orchestrator.deleteVM(vmId);

    logger.info(`VM deleted: ${vmId}`);

    res.json({ message: 'VM deleted' });
  } catch (error) {
    logger.error('VM deletion error', error);
    res.status(500).json({ error: 'Failed to delete VM' });
  }
});

// Create nested VM
vmRoutes.post('/:vmId/nested', async (req: Request, res: Response) => {
  try {
    const { vmId } = req.params;
    const { name, cpu, memory, disk = 20 } = req.body;

    if (!name || !cpu || !memory) {
      return res.status(400).json({ error: 'Missing required VM configuration' });
    }

    const orchestrator = getVMOrchestrator();
    const nestedVmId = uuidv4();

    const vmState = await orchestrator.createNestedVM(vmId, {
      id: nestedVmId,
      name,
      cpu,
      memory,
      disk,
      hypervisor: 'virtualbox',
      network: { type: 'internal' },
    });

    logger.info(`Nested VM created: ${nestedVmId} inside ${vmId}`);

    res.status(201).json(vmState);
  } catch (error) {
    logger.error('Nested VM creation error', error);
    res.status(500).json({ error: 'Failed to create nested VM' });
  }
});

// List nested VMs
vmRoutes.get('/:vmId/nested', async (req: Request, res: Response) => {
  try {
    const { vmId } = req.params;
    const orchestrator = getVMOrchestrator();

    const nestedVMs = await orchestrator.getNestedVMs(vmId);

    res.json(nestedVMs);
  } catch (error) {
    logger.error('Nested VMs list error', error);
    res.status(500).json({ error: 'Failed to list nested VMs' });
  }
});
