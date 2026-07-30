import { Server } from 'http';
import https from 'https';
import { Logger } from '../utils/logger';

const logger = new Logger();

export interface NetworkSecurityConfig {
  enableTls: boolean;
  tlsCert: string;
  tlsKey: string;
  minTlsVersion: string;
  cipherSuites: string[];
  enableHsts: boolean;
  hstsMaxAge: number;
}

export class NetworkSecurityLayer {
  private config: NetworkSecurityConfig;
  private allowedOrigins: Set<string> = new Set();
  private serviceRegistry: Map<string, ServiceInfo> = new Map();

  constructor(config: Partial<NetworkSecurityConfig> = {}) {
    this.config = {
      enableTls: config.enableTls !== false,
      tlsCert: config.tlsCert || '/etc/ssl/certs/server.crt',
      tlsKey: config.tlsKey || '/etc/ssl/private/server.key',
      minTlsVersion: config.minTlsVersion || 'TLSv1.2',
      cipherSuites: config.cipherSuites || this.getDefaultCipherSuites(),
      enableHsts: config.enableHsts !== false,
      hstsMaxAge: config.hstsMaxAge || 31536000, // 1 year
    };
  }

  // Create HTTPS server with security configuration
  createSecureServer(app: any, port: number = 3000): Server {
    let server: Server;

    if (this.config.enableTls) {
      try {
        const fs = require('fs');
        const key = fs.readFileSync(this.config.tlsKey);
        const cert = fs.readFileSync(this.config.tlsCert);

        const httpsOptions = {
          key,
          cert,
          minVersion: this.getTlsVersion(this.config.minTlsVersion),
          ciphers: this.config.cipherSuites.join(':'),
          honorCipherOrder: true,
          handshakeTimeout: 10000,
        };

        server = https.createServer(httpsOptions, app);
        logger.info('HTTPS server created with TLS enabled');
      } catch (error) {
        logger.error('Failed to load TLS certificates, falling back to HTTP', error);
        const http = require('http');
        server = http.createServer(app);
      }
    } else {
      const http = require('http');
      server = http.createServer(app);
      logger.warn('HTTP server created without TLS (development only)');
    }

    return server;
  }

  // Register internal services
  registerService(name: string, info: ServiceInfo): void {
    this.serviceRegistry.set(name, info);
    logger.info(`Service registered: ${name} at ${info.host}:${info.port}`);
  }

  // Verify inter-service communication
  verifyServiceAuth(sourceService: string, targetService: string, token: string): boolean {
    const source = this.serviceRegistry.get(sourceService);
    const target = this.serviceRegistry.get(targetService);

    if (!source || !target) {
      logger.warn(`Service communication attempt with unregistered service`);
      return false;
    }

    // Verify token (implementation depends on auth mechanism)
    return this.validateServiceToken(token, sourceService, targetService);
  }

  // Add CORS configuration
  addCorsOrigin(origin: string): void {
    this.allowedOrigins.add(origin);
  }

  // Get allowed origins
  getAllowedOrigins(): string[] {
    return Array.from(this.allowedOrigins);
  }

  // Generate service mesh configuration
  generateServiceMeshConfig() {
    return {
      services: Array.from(this.serviceRegistry.entries()).map(([name, info]) => ({
        name,
        host: info.host,
        port: info.port,
        protocol: 'https',
        healthCheck: {
          path: '/health',
          interval: '30s',
          timeout: '5s',
        },
        rateLimit: {
          requests: info.rateLimit || 1000,
          window: '1m',
        },
        timeout: info.timeout || 30000,
      })),
      security: {
        tlsEnabled: this.config.enableTls,
        minTlsVersion: this.config.minTlsVersion,
        mtlsEnabled: true,
      },
    };
  }

  // Certificate pinning for critical services
  pinCertificate(service: string, certificateHash: string): void {
    const serviceInfo = this.serviceRegistry.get(service);
    if (serviceInfo) {
      serviceInfo.certificateHash = certificateHash;
      logger.info(`Certificate pinned for service: ${service}`);
    }
  }

  // Validate certificate pinning
  validateCertificatePinning(service: string, certificateHash: string): boolean {
    const serviceInfo = this.serviceRegistry.get(service);
    if (!serviceInfo || !serviceInfo.certificateHash) {
      return true; // Not pinned
    }
    return serviceInfo.certificateHash === certificateHash;
  }

  // Rate limiting per service
  setServiceRateLimit(service: string, requestsPerMinute: number): void {
    const serviceInfo = this.serviceRegistry.get(service);
    if (serviceInfo) {
      serviceInfo.rateLimit = requestsPerMinute;
    }
  }

  // Get default secure cipher suites
  private getDefaultCipherSuites(): string[] {
    return [
      'TLS_AES_256_GCM_SHA384',
      'TLS_CHACHA20_POLY1305_SHA256',
      'TLS_AES_128_GCM_SHA256',
      'ECDHE-ECDSA-AES256-GCM-SHA384',
      'ECDHE-RSA-AES256-GCM-SHA384',
      'ECDHE-ECDSA-CHACHA20-POLY1305',
      'ECDHE-RSA-CHACHA20-POLY1305',
      'ECDHE-ECDSA-AES128-GCM-SHA256',
      'ECDHE-RSA-AES128-GCM-SHA256',
    ];
  }

  // Convert TLS version string to crypto constant
  private getTlsVersion(version: string): string {
    const versionMap: Record<string, string> = {
      TLSv1: 'TLSv1',
      TLSv1_1: 'TLSv1_1',
      TLSv1_2: 'TLSv1_2',
      TLSv1_3: 'TLSv1_3',
    };
    return versionMap[version] || 'TLSv1_2';
  }

  // Validate service token (implement based on your auth mechanism)
  private validateServiceToken(token: string, source: string, target: string): boolean {
    // This is a placeholder - implement based on your service authentication
    // For now, just check that token is not empty
    return token && token.length > 0;
  }

  getSecurityStatus() {
    return {
      tlsEnabled: this.config.enableTls,
      minTlsVersion: this.config.minTlsVersion,
      registeredServices: this.serviceRegistry.size,
      allowedOrigins: this.allowedOrigins.size,
      services: Array.from(this.serviceRegistry.keys()),
    };
  }
}

export interface ServiceInfo {
  host: string;
  port: number;
  protocol?: string;
  rateLimit?: number;
  timeout?: number;
  certificateHash?: string;
}

// Network isolation/segmentation
export class NetworkSegmentation {
  private segments: Map<string, NetworkSegment> = new Map();

  addSegment(name: string, config: NetworkSegmentConfig): void {
    this.segments.set(name, {
      name,
      vlan: config.vlan,
      subnet: config.subnet,
      gateway: config.gateway,
      rules: config.rules || [],
    });
  }

  getSegment(name: string): NetworkSegment | undefined {
    return this.segments.get(name);
  }

  // Check if traffic is allowed between segments
  isTrafficAllowed(fromSegment: string, toSegment: string, port: number): boolean {
    const from = this.segments.get(fromSegment);
    const to = this.segments.get(toSegment);

    if (!from || !to) {
      return false;
    }

    // Check firewall rules
    for (const rule of from.rules) {
      if (rule.allowedSegments?.includes(toSegment) && rule.allowedPorts?.includes(port)) {
        return true;
      }
    }

    return false;
  }

  getSegmentationStatus() {
    return {
      totalSegments: this.segments.size,
      segments: Array.from(this.segments.values()).map((seg) => ({
        name: seg.name,
        vlan: seg.vlan,
        subnet: seg.subnet,
        rules: seg.rules.length,
      })),
    };
  }
}

export interface NetworkSegment {
  name: string;
  vlan: number;
  subnet: string;
  gateway: string;
  rules: FirewallRule[];
}

export interface NetworkSegmentConfig {
  vlan: number;
  subnet: string;
  gateway: string;
  rules?: FirewallRule[];
}

export interface FirewallRule {
  name: string;
  allowedSegments?: string[];
  allowedPorts?: number[];
  protocol?: string;
  action: 'allow' | 'deny';
}

export function createNetworkSecurityLayer(config?: Partial<NetworkSecurityConfig>) {
  return new NetworkSecurityLayer(config);
}

export function createNetworkSegmentation(): NetworkSegmentation {
  return new NetworkSegmentation();
}
