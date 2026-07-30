import { EventEmitter } from 'events';
import { exec } from 'child_process';
import { promisify } from 'util';
import { Logger } from '../utils/logger';

const execAsync = promisify(exec);

export interface VMConfig {
  id: string;
  name: string;
  cpu: number;
  memory: number; // MB
  disk: number; // GB
  hypervisor: 'virtualbox' | 'kvm' | 'docker';
  network: {
    type: 'nat' | 'bridge' | 'internal';
    name?: string;
  };
  parent?: string; // For nested VMs
}

export interface VMState {
  id: string;
  name: string;
  status: 'stopped' | 'running' | 'paused' | 'error';
  memory: number;
  cpu: number;
  uptime?: number;
  ip?: string;
}

export class VMOrchestrator extends EventEmitter {
  private logger = new Logger();
  private vms: Map<string, VMState> = new Map();
  private configs: Map<string, VMConfig> = new Map();
  private hypervisor: string;

  constructor(hypervisor: string = 'virtualbox') {
    super();
    this.hypervisor = hypervisor;
  }

  async initialize() {
    this.logger.info(`Initializing VM Orchestrator with ${this.hypervisor}`);

    // Check if hypervisor is available
    try {
      if (this.hypervisor === 'virtualbox') {
        await execAsync('vboxmanage --version');
      } else if (this.hypervisor === 'kvm') {
        await execAsync('virsh version');
      } else if (this.hypervisor === 'docker') {
        await execAsync('docker --version');
      }

      this.logger.info(`${this.hypervisor} is available`);
    } catch (error) {
      this.logger.warn(`${this.hypervisor} is not available`, error);
    }
  }

  async createVM(config: VMConfig): Promise<VMState> {
    this.logger.info(`Creating VM: ${config.name}`);

    this.configs.set(config.id, config);

    const vmState: VMState = {
      id: config.id,
      name: config.name,
      status: 'stopped',
      memory: config.memory,
      cpu: config.cpu,
    };

    this.vms.set(config.id, vmState);

    // Create VM based on hypervisor
    try {
      if (this.hypervisor === 'virtualbox') {
        await this.createVirtualBoxVM(config);
      } else if (this.hypervisor === 'kvm') {
        await this.createKVMVM(config);
      } else if (this.hypervisor === 'docker') {
        await this.createDockerVM(config);
      }

      this.emit('vm-created', vmState);
      return vmState;
    } catch (error) {
      this.logger.error(`Failed to create VM ${config.id}`, error);
      vmState.status = 'error';
      throw error;
    }
  }

  private async createVirtualBoxVM(config: VMConfig) {
    try {
      // Create VM
      await execAsync(
        `VBoxManage createvm --name "${config.name}" --ostype Linux --register`
      );

      // Configure resources
      await execAsync(
        `VBoxManage modifyvm "${config.name}" --cpus ${config.cpu} --memory ${config.memory}`
      );

      // Configure network
      await execAsync(
        `VBoxManage modifyvm "${config.name}" --nic1 ${config.network.type === 'nat' ? 'nat' : 'bridged'}`
      );

      this.logger.info(`VirtualBox VM created: ${config.name}`);
    } catch (error) {
      this.logger.error(`VirtualBox VM creation failed`, error);
      throw error;
    }
  }

  private async createKVMVM(config: VMConfig) {
    // KVM/QEMU implementation
    try {
      const vncPort = 5900 + Math.floor(Math.random() * 100);

      const qemuArgs = [
        'qemu-system-x86_64',
        `-name "${config.name}"`,
        `-m ${config.memory}`,
        `-smp cpus=${config.cpu}`,
        `-vnc :${vncPort}`,
        `-net ${config.network.type}`,
        `-daemonize`,
      ].join(' ');

      await execAsync(qemuArgs);

      this.logger.info(`KVM VM created: ${config.name} (VNC port: ${vncPort})`);
    } catch (error) {
      this.logger.error(`KVM VM creation failed`, error);
      throw error;
    }
  }

  private async createDockerVM(config: VMConfig) {
    // Docker implementation (for containerized environments)
    try {
      const dockerArgs = [
        'docker run',
        `-d`,
        `--name "${config.name}"`,
        `-m ${config.memory}m`,
        `--cpus ${config.cpu}`,
        `--network ${config.network.name || 'dss-network'}`,
        `ubuntu:22.04`,
        'sleep infinity',
      ].join(' ');

      await execAsync(dockerArgs);

      this.logger.info(`Docker container created: ${config.name}`);
    } catch (error) {
      this.logger.error(`Docker container creation failed`, error);
      throw error;
    }
  }

  async startVM(vmId: string): Promise<void> {
    const vmState = this.vms.get(vmId);
    if (!vmState) {
      throw new Error(`VM ${vmId} not found`);
    }

    this.logger.info(`Starting VM: ${vmState.name}`);

    try {
      if (this.hypervisor === 'virtualbox') {
        await execAsync(`VBoxManage startvm "${vmState.name}" --type headless`);
      } else if (this.hypervisor === 'kvm') {
        // KVM VMs are started on creation, this would manage existing VMs
      } else if (this.hypervisor === 'docker') {
        await execAsync(`docker start "${vmState.name}"`);
      }

      vmState.status = 'running';
      vmState.uptime = 0;
      this.emit('vm-started', vmState);
    } catch (error) {
      this.logger.error(`Failed to start VM ${vmId}`, error);
      throw error;
    }
  }

  async stopVM(vmId: string): Promise<void> {
    const vmState = this.vms.get(vmId);
    if (!vmState) {
      throw new Error(`VM ${vmId} not found`);
    }

    this.logger.info(`Stopping VM: ${vmState.name}`);

    try {
      if (this.hypervisor === 'virtualbox') {
        await execAsync(`VBoxManage controlvm "${vmState.name}" poweroff`);
      } else if (this.hypervisor === 'docker') {
        await execAsync(`docker stop "${vmState.name}"`);
      }

      vmState.status = 'stopped';
      this.emit('vm-stopped', vmState);
    } catch (error) {
      this.logger.error(`Failed to stop VM ${vmId}`, error);
      throw error;
    }
  }

  async deleteVM(vmId: string): Promise<void> {
    const vmState = this.vms.get(vmId);
    if (!vmState) {
      throw new Error(`VM ${vmId} not found`);
    }

    this.logger.info(`Deleting VM: ${vmState.name}`);

    try {
      if (vmState.status === 'running') {
        await this.stopVM(vmId);
      }

      if (this.hypervisor === 'virtualbox') {
        await execAsync(`VBoxManage unregistervm "${vmState.name}" --delete`);
      } else if (this.hypervisor === 'docker') {
        await execAsync(`docker rm -f "${vmState.name}"`);
      }

      this.vms.delete(vmId);
      this.configs.delete(vmId);
      this.emit('vm-deleted', vmState);
    } catch (error) {
      this.logger.error(`Failed to delete VM ${vmId}`, error);
      throw error;
    }
  }

  async pauseVM(vmId: string): Promise<void> {
    const vmState = this.vms.get(vmId);
    if (!vmState) {
      throw new Error(`VM ${vmId} not found`);
    }

    try {
      if (this.hypervisor === 'virtualbox') {
        await execAsync(`VBoxManage controlvm "${vmState.name}" pause`);
      }

      vmState.status = 'paused';
      this.emit('vm-paused', vmState);
    } catch (error) {
      this.logger.error(`Failed to pause VM ${vmId}`, error);
      throw error;
    }
  }

  async resumeVM(vmId: string): Promise<void> {
    const vmState = this.vms.get(vmId);
    if (!vmState) {
      throw new Error(`VM ${vmId} not found`);
    }

    try {
      if (this.hypervisor === 'virtualbox') {
        await execAsync(`VBoxManage controlvm "${vmState.name}" resume`);
      }

      vmState.status = 'running';
      this.emit('vm-resumed', vmState);
    } catch (error) {
      this.logger.error(`Failed to resume VM ${vmId}`, error);
      throw error;
    }
  }

  listVMs(): VMState[] {
    return Array.from(this.vms.values());
  }

  getVMState(vmId: string): VMState | undefined {
    return this.vms.get(vmId);
  }

  async createNestedVM(parentVmId: string, config: VMConfig): Promise<VMState> {
    const parentVM = this.vms.get(parentVmId);
    if (!parentVM) {
      throw new Error(`Parent VM ${parentVmId} not found`);
    }

    this.logger.info(`Creating nested VM: ${config.name} inside ${parentVM.name}`);

    config.parent = parentVmId;

    // For nested VMs, we need to ensure the parent VM is running
    if (parentVM.status !== 'running') {
      throw new Error(`Parent VM must be running to create nested VMs`);
    }

    // Create the nested VM
    return this.createVM(config);
  }

  async getNestedVMs(parentVmId: string): Promise<VMState[]> {
    return Array.from(this.vms.values()).filter((vm) => {
      const config = this.configs.get(vm.id);
      return config?.parent === parentVmId;
    });
  }
}

let orchestrator: VMOrchestrator;

export async function initVMOrchestrator(hypervisor?: string): Promise<VMOrchestrator> {
  orchestrator = new VMOrchestrator(hypervisor);
  await orchestrator.initialize();
  return orchestrator;
}

export function getVMOrchestrator(): VMOrchestrator {
  if (!orchestrator) {
    throw new Error('VM Orchestrator not initialized');
  }
  return orchestrator;
}
