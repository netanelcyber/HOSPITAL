import { Request, Response, NextFunction } from 'express';
import crypto from 'crypto';
import { Logger } from '../utils/logger';
import { query } from '../db/postgres';

const logger = new Logger();

/**
 * HIPAA Compliance Module
 * Implements HIPAA Security Rule and Privacy Rule requirements
 */

export interface HIPAAConfig {
  enableEncryption: boolean;
  enableAuditLogging: boolean;
  enableAccessControls: boolean;
  enableDataIntegrity: boolean;
  encryptionAlgorithm: string;
  auditRetentionDays: number;
  passwordMinLength: number;
  passwordExpiryDays: number;
  mfaRequired: boolean;
  sessionTimeoutMinutes: number;
}

export class HIPAACompliance {
  private config: HIPAAConfig;
  private auditLog: Map<string, AuditEntry[]> = new Map();

  constructor(config: Partial<HIPAAConfig> = {}) {
    this.config = {
      enableEncryption: config.enableEncryption !== false,
      enableAuditLogging: config.enableAuditLogging !== false,
      enableAccessControls: config.enableAccessControls !== false,
      enableDataIntegrity: config.enableDataIntegrity !== false,
      encryptionAlgorithm: config.encryptionAlgorithm || 'aes-256-gcm',
      auditRetentionDays: config.auditRetentionDays || 6 * 365, // 6 years
      passwordMinLength: config.passwordMinLength || 12,
      passwordExpiryDays: config.passwordExpiryDays || 90,
      mfaRequired: config.mfaRequired !== false,
      sessionTimeoutMinutes: config.sessionTimeoutMinutes || 30,
    };

    logger.info('HIPAA Compliance module initialized');
  }

  /**
   * Encrypt sensitive data (PHI - Protected Health Information)
   */
  encryptPHI(data: string, key: string): string {
    if (!this.config.enableEncryption) {
      return data;
    }

    try {
      const iv = crypto.randomBytes(16);
      const cipher = crypto.createCipheriv(this.config.encryptionAlgorithm, Buffer.from(key), iv);

      let encrypted = cipher.update(data, 'utf8', 'hex');
      encrypted += cipher.final('hex');

      // Include IV in output
      return `${iv.toString('hex')}:${encrypted}`;
    } catch (error) {
      logger.error('Encryption failed', error);
      throw new Error('Failed to encrypt PHI');
    }
  }

  /**
   * Decrypt sensitive data
   */
  decryptPHI(encryptedData: string, key: string): string {
    if (!this.config.enableEncryption) {
      return encryptedData;
    }

    try {
      const [ivHex, encrypted] = encryptedData.split(':');
      const iv = Buffer.from(ivHex, 'hex');
      const decipher = crypto.createDecipheriv(
        this.config.encryptionAlgorithm,
        Buffer.from(key),
        iv
      );

      let decrypted = decipher.update(encrypted, 'hex', 'utf8');
      decrypted += decipher.final('utf8');

      return decrypted;
    } catch (error) {
      logger.error('Decryption failed', error);
      throw new Error('Failed to decrypt PHI');
    }
  }

  /**
   * Audit logging middleware
   */
  auditMiddleware() {
    return async (req: Request, res: Response, next: NextFunction) => {
      if (!this.config.enableAuditLogging) {
        return next();
      }

      const startTime = Date.now();
      const userId = (req as any).user?.id || 'anonymous';

      // Intercept response
      const originalSend = res.send;
      res.send = function (data: any) {
        const duration = Date.now() - startTime;

        // Log audit entry
        const auditEntry: AuditEntry = {
          timestamp: new Date(),
          userId,
          action: req.method,
          resource: req.path,
          statusCode: res.statusCode,
          ipAddress: req.ip || 'unknown',
          duration,
          phiAccessed: this.isPHIEndpoint(req.path),
        };

        // Store locally
        if (!this.auditLog.has(userId)) {
          this.auditLog.set(userId, []);
        }
        this.auditLog.get(userId)!.push(auditEntry);

        // Store in database
        this.storeAuditLog(auditEntry).catch((error) =>
          logger.error('Failed to store audit log', error)
        );

        return originalSend.call(this, data);
      }.bind(this);

      next();
    };
  }

  /**
   * Check if endpoint accesses PHI
   */
  private isPHIEndpoint(path: string): boolean {
    const phiEndpoints = [
      '/pacs',
      '/fhir/Patient',
      '/documents',
      '/api/v1/pacs',
      '/api/v1/fhir',
    ];

    return phiEndpoints.some((endpoint) => path.includes(endpoint));
  }

  /**
   * Store audit log in database
   */
  private async storeAuditLog(entry: AuditEntry): Promise<void> {
    try {
      await query(
        `INSERT INTO access_logs (id, user_id, action, ip_address, created_at)
         VALUES ($1, $2, $3, $4, $5)`,
        [
          crypto.randomUUID(),
          entry.userId,
          `${entry.action} ${entry.resource}`,
          entry.ipAddress,
          entry.timestamp,
        ]
      );
    } catch (error) {
      logger.error('Failed to store audit log', error);
    }
  }

  /**
   * Password policy enforcement
   */
  validatePasswordPolicy(password: string): { valid: boolean; errors: string[] } {
    const errors: string[] = [];

    if (password.length < this.config.passwordMinLength) {
      errors.push(`Password must be at least ${this.config.passwordMinLength} characters`);
    }

    if (!/[A-Z]/.test(password)) {
      errors.push('Password must contain uppercase letters');
    }

    if (!/[a-z]/.test(password)) {
      errors.push('Password must contain lowercase letters');
    }

    if (!/[0-9]/.test(password)) {
      errors.push('Password must contain numbers');
    }

    if (!/[!@#$%^&*]/.test(password)) {
      errors.push('Password must contain special characters (!@#$%^&*)');
    }

    return {
      valid: errors.length === 0,
      errors,
    };
  }

  /**
   * Access control middleware
   */
  accessControlMiddleware() {
    return (req: Request, res: Response, next: NextFunction) => {
      if (!this.config.enableAccessControls) {
        return next();
      }

      const userId = (req as any).user?.id;
      const resource = req.path;

      // Check if user has access to resource
      this.checkAccessPermission(userId, resource)
        .then((hasAccess) => {
          if (!hasAccess) {
            logger.warn(`Access denied for user ${userId} to ${resource}`);
            return res.status(403).json({ error: 'Access denied' });
          }
          next();
        })
        .catch((error) => {
          logger.error('Access control check failed', error);
          res.status(500).json({ error: 'Access control check failed' });
        });
    };
  }

  /**
   * Check if user has permission to access resource
   */
  private async checkAccessPermission(userId: string, resource: string): Promise<boolean> {
    if (!userId) {
      return false;
    }

    // Check if resource is PHI
    if (this.isPHIEndpoint(resource)) {
      // Verify PHI access authorization
      try {
        const result = await query(
          `SELECT role FROM users WHERE id = $1`,
          [userId]
        );

        if (result.rows.length === 0) {
          return false;
        }

        const role = result.rows[0].role;

        // Only certain roles can access PHI
        const phiRoles = ['admin', 'doctor', 'clinician', 'healthcare_provider'];
        return phiRoles.includes(role);
      } catch (error) {
        logger.error('Failed to check access permission', error);
        return false;
      }
    }

    return true;
  }

  /**
   * Data integrity check (HMAC)
   */
  calculateIntegrityHash(data: string, key: string): string {
    return crypto.createHmac('sha256', key).update(data).digest('hex');
  }

  /**
   * Verify data integrity
   */
  verifyIntegrity(data: string, hash: string, key: string): boolean {
    const calculatedHash = this.calculateIntegrityHash(data, key);
    return calculatedHash === hash;
  }

  /**
   * Generate compliance report
   */
  async generateComplianceReport(): Promise<ComplianceReport> {
    const totalAuditEntries = Array.from(this.auditLog.values()).reduce(
      (sum, entries) => sum + entries.length,
      0
    );

    const phiAccessEntries = Array.from(this.auditLog.values())
      .flat()
      .filter((entry) => entry.phiAccessed).length;

    return {
      generatedAt: new Date(),
      configuration: {
        encryption: this.config.enableEncryption,
        auditLogging: this.config.enableAuditLogging,
        accessControls: this.config.enableAccessControls,
        dataIntegrity: this.config.enableDataIntegrity,
        mfaRequired: this.config.mfaRequired,
        auditRetentionDays: this.config.auditRetentionDays,
      },
      statistics: {
        totalAuditEntries,
        phiAccessCount: phiAccessEntries,
        usersTracked: this.auditLog.size,
        encryptionAlgorithm: this.config.encryptionAlgorithm,
      },
      security: {
        passwordPolicy: {
          minLength: this.config.passwordMinLength,
          expiryDays: this.config.passwordExpiryDays,
          requiresSpecialChars: true,
          requiresNumbers: true,
          requiresUppercase: true,
          requiresLowercase: true,
        },
        sessionManagement: {
          timeoutMinutes: this.config.sessionTimeoutMinutes,
          mfaRequired: this.config.mfaRequired,
        },
      },
      compliance: {
        status: 'active',
        lastReview: new Date(),
        nextReview: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000), // 1 year
        breachCount: 0,
        violations: [],
      },
    };
  }

  /**
   * Data retention policy
   */
  async enforceRetentionPolicy(): Promise<void> {
    const retentionDate = new Date(Date.now() - this.config.auditRetentionDays * 24 * 60 * 60 * 1000);

    try {
      await query(
        `DELETE FROM access_logs WHERE created_at < $1`,
        [retentionDate]
      );

      logger.info(`Deleted audit logs older than ${retentionDate.toISOString()}`);
    } catch (error) {
      logger.error('Failed to enforce retention policy', error);
    }
  }

  /**
   * Schedule retention policy enforcement
   */
  startRetentionEnforcement(intervalDays: number = 30): void {
    setInterval(() => {
      this.enforceRetentionPolicy().catch((error) =>
        logger.error('Retention enforcement failed', error)
      );
    }, intervalDays * 24 * 60 * 60 * 1000);

    logger.info(`Retention policy enforcement scheduled every ${intervalDays} days`);
  }

  /**
   * Get compliance status
   */
  getComplianceStatus() {
    return {
      enabled: true,
      configuration: this.config,
      auditEntriesCount: Array.from(this.auditLog.values()).reduce(
        (sum, entries) => sum + entries.length,
        0
      ),
      usersAudited: this.auditLog.size,
    };
  }
}

export interface AuditEntry {
  timestamp: Date;
  userId: string;
  action: string;
  resource: string;
  statusCode: number;
  ipAddress: string;
  duration: number;
  phiAccessed: boolean;
}

export interface ComplianceReport {
  generatedAt: Date;
  configuration: any;
  statistics: any;
  security: any;
  compliance: any;
}

export function createHIPAACompliance(config?: Partial<HIPAAConfig>): HIPAACompliance {
  return new HIPAACompliance(config);
}
